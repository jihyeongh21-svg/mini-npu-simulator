# main.py 단계별 해부

`main.py`가 어떤 순서로, 왜 그렇게 작성됐는지 설명하는 문서입니다. 위에서 아래로 "작은 부품 → 검증 → 모드 → 진입점" 순서로 쌓은 구조를 그대로 따라갑니다.

## 0. 전체 구조

```
main()
 ├─ 모드 1: mode_user_input()  ← read_matrix → mac → judge_scores → measure_mac
 └─ 모드 2: mode_json()
      ├─ load_filters()        ← normalize_label, validate_matrix
      ├─ evaluate_case() × N   ← normalize_label, validate_matrix, mac, judge_scores
      ├─ performance_table()   ← measure_mac, make_cross
      └─ 결과 리포트 출력
```

| 계층 | 함수 | 하는 일 |
| --- | --- | --- |
| 핵심 연산 | `normalize_label`, `mac`, `judge_scores`, `measure_mac` | 입출력과 무관한 순수 계산 |
| 검증 | `validate_matrix`, `load_filters`, `evaluate_case` | 잘못된 데이터를 예외 → FAIL 사유로 변환 |
| 모드 | `read_matrix`, `mode_user_input`, `performance_table`, `mode_json` | 사용자와 상호작용, 출력 |
| 보너스 | `make_cross`, `make_x` | N×N 패턴 생성 |

코드에는 섹션 구분 주석(`# ---------- ... ----------`)과 "왜 이렇게 했는지"를 적은 주석이 달려 있습니다. 이 문서와 함께 `main.py`를 위에서부터 읽으면 같은 순서로 따라갈 수 있습니다.

설계 원칙은 두 가지입니다. 계산 함수는 print/input을 하지 않아 시간 측정에 I/O가 섞이지 않고, 오류는 `ValueError`로 올려서 맨 바깥(케이스 단위)에서 한 번에 잡습니다.

## 1. 상수와 import

```python
import json, os, re, time
EPSILON = 1e-9
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")
```

- 모두 표준 라이브러리입니다(`json` 파싱, `re` 키 형식 검사, `time` 측정, `os` 경로).
- `EPSILON`은 동점 판정 기준입니다. `0.1`, `0.9` 같은 값은 2진 부동소수점으로 정확히 표현되지 않아 `==` 비교가 불안정하기 때문에 "차이가 1e-9보다 작으면 같다"로 정의합니다.
- `DATA_FILE`은 실행 위치(cwd)가 아니라 `main.py`가 있는 폴더를 기준으로 합니다. 다른 폴더에서 실행해도 `data.json`을 찾습니다.

## 2. normalize_label: 표기 통일

```python
key = str(label).strip().lower()
if key in ("+", "cross"): return "Cross"
if key == "x": return "X"
raise ValueError(...)
```

- expected는 `+`/`x`, 필터 키는 `cross`/`x`로 표기가 달라서 내부에서는 `Cross`/`X` 두 값으로 통일합니다.
- `strip().lower()`로 공백과 대소문자 차이(`"X"`, `" x "`)를 흡수합니다.
- 알 수 없는 라벨은 조용히 넘기지 않고 `ValueError`를 냅니다. 오타가 거짓 PASS가 되는 것을 막기 위해서입니다.

## 3. mac: 이 프로그램의 심장

```python
total = 0.0
for i in range(len(pattern)):
    for j in range(len(pattern[i])):
        total += pattern[i][j] * filt[i][j]
return total
```

- 같은 위치 값끼리 곱하고 전부 더합니다(Multiply-Accumulate).
- 이중 for문을 쓴 이유는 미션이 NumPy와 벡터화 연산을 금지했기 때문입니다. 곱셈과 덧셈이 각각 N²번이므로 O(N²)입니다.
- 손으로 확인하면 3×3 십자가 입력에 십자가 필터는 겹치는 칸이 5개라 5점, X 필터는 가운데 1칸만 겹쳐 1점입니다. 모드 1 테스트 결과(A 5, B 1)와 같습니다.

## 4. judge_scores: 동점 처리

```python
if abs(score_a - score_b) < EPSILON: return "UNDECIDED"
return name_a if score_a > score_b else name_b
```

- 동점을 먼저 검사한 뒤 큰 쪽을 고릅니다. 순서가 반대면 동점이 항상 B로 판정되는 버그가 생깁니다.
- `name_a`, `name_b` 인자 덕분에 모드 1은 `A/B`, 모드 2는 `Cross/X`로 같은 함수를 재사용합니다.

## 5. measure_mac: 시간 측정

```python
start = time.perf_counter()
for _ in range(repeat): mac(pattern, filt)
return (time.perf_counter() - start) / repeat * 1000.0
```

- `perf_counter`는 짧은 구간 측정용 고해상도 타이머입니다.
- 측정 구간에 `mac`만 넣고 print/input은 넣지 않아 I/O 시간이 섞이지 않습니다.
- 10번 반복해 평균을 내는 이유는 마이크로초 단위 측정이 1회로는 흔들리기 때문입니다. 마지막에 `* 1000`으로 초를 ms로 바꿉니다.

## 6. validate_matrix: 방어선

검사 순서는 다음과 같습니다.

1. 비어 있지 않은 리스트인지
2. 각 행이 리스트이고 길이가 행 수(N)와 같은지 (정사각)
3. 모든 값이 숫자인지 (`bool`은 `int`의 하위 타입이라 따로 제외)
4. `size`가 주어지면 N과 일치하는지

실패하면 사유가 담긴 `ValueError`를 냅니다. 이 검사가 `mac` 앞에 있어서 크기 불일치 입력이 `IndexError`로 프로그램을 죽이지 않습니다. 사유 문자열이 그대로 콘솔의 FAIL 사유가 됩니다.

## 7. load_filters: 필터 스키마 검증

- 입력: `{"size_5": {"cross": [...], "x": [...]}, ...}` → 출력: `{5: {"Cross": M, "X": M}, ...}`
- 키는 정규식 `size_(\d+)`로 검사하고 숫자 N을 뽑습니다. 키 형식이 다르면 오류입니다.
- 내부 라벨은 `normalize_label`로 통일하고, Cross와 X가 둘 다 있어야 합니다.
- 각 행렬은 `validate_matrix(mat, size)`로 키의 N과 실제 크기가 맞는지 확인합니다. 예를 들어 `size_5` 필터가 4×4이면 여기서 걸립니다.

## 8. evaluate_case: 케이스 단위 안전 처리

흐름은 다음과 같습니다.

```
키 이름 검사(size_N_xxx) → input/expected 키 존재 → expected 정규화
→ 패턴 검증(크기 N) → 해당 크기 필터 존재 확인
→ Cross·X 점수 계산 → judge_scores → expected와 비교
```

- 함수 전체가 `try ... except (ValueError, TypeError, KeyError)`로 감싸져 있어, 어떤 오류든 해당 케이스의 `reason`에 기록되고 `pass=False`가 됩니다. 이것이 "비정상 종료 금지" 요구의 구현입니다.
- 결과는 `{name, pass, reason, scores, judge}` 딕셔너리라서 출력 코드는 이 값만 읽으면 됩니다.
- 판정이 `UNDECIDED`이면 expected와 무관하게 FAIL이고, 사유에 동점 규칙을 적습니다.

### 실제 데이터로 따라가 보기: `size_5_1`

| 단계 | 값 |
| --- | --- |
| expected | `x` → `X` |
| 입력 | 5×5 X 모양 (대각선 9칸이 1.0) |
| Cross 필터와 MAC | 겹치는 칸은 중앙 1칸, 값 0.9 → **0.9** |
| X 필터와 MAC | 9칸 × 0.1 → **0.9** |
| 판정 | 차이 0 < 1e-9 → `UNDECIDED` → FAIL |

필터 가중치가 우연히 맞아떨어진 동점이라 코드 결함이 아닙니다.

### 제공된 data.json 6건 전체 추적

| 케이스 | 입력 모양 | Cross | X | 판정 | expected | 결과 | 이유 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| size_5_1 | X | 0.9 | 0.9 | UNDECIDED | x | FAIL | 동점 |
| size_5_2 | 십자가 | 8.9 | 0.1 | Cross | + | PASS | |
| size_13_1 | X | 0.3 | 14.7 | X | x | PASS | |
| size_13_2 | 십자가 | 7.5 | 7.5 | UNDECIDED | + | FAIL | 동점 |
| size_25_1 | X | 4.9 | 4.9 | UNDECIDED | x | FAIL | 동점 |
| size_25_2 | 십자가 | 52.9 | 0.1 | Cross | + | PASS | |

읽는 법: PASS 케이스는 점수 차이가 크고(8.9 vs 0.1), FAIL 케이스는 두 점수가 정확히 같습니다. 즉 "틀린 판정"이 아니라 "판정할 수 없음"이 실패 원인입니다.

## 9. 모드 1: read_matrix와 mode_user_input

- `read_matrix`는 `n`줄을 읽어 `split()`으로 쪼개고, 개수가 `n`이 아니면 `ValueError`, 숫자 변환 실패(`float`)도 `ValueError`입니다.
- 오류가 나면 안내 메시지를 출력하고 `while True`로 그 행렬을 처음부터 다시 입력받습니다. 프로그램은 종료되지 않습니다.
- `mode_user_input`은 필터 A → 필터 B → 패턴을 읽고, 점수 2개, 연산 시간, 판정을 출력합니다. `UNDECIDED`는 "판정 불가"로 표시합니다.

## 10. 모드 2: performance_table과 mode_json

`performance_table`
- 3, 5, 13, 25 크기마다 전부 1로 채운 N×N 패턴과 필터로 `measure_mac`을 호출합니다. 필터는 `data.json`에 있으면 그것을, 없으면(3×3) `make_cross`로 만듭니다.
- 연산 횟수 열은 `n * n`입니다. 이론값(N²)과 실측 시간을 나란히 보여주기 위해서입니다.

`mode_json` 순서
1. 파일을 읽고 `load_filters`로 필터를 검증합니다. 파일이 없거나 JSON이 깨져 있으면(`OSError`, `ValueError`, `JSONDecodeError`는 ValueError의 하위 클래스) 메시지만 출력하고 돌아갑니다.
2. `patterns`의 각 케이스를 `evaluate_case`로 평가하고 한 줄씩 `PASS/FAIL`을 출력합니다.
3. 성능 표를 출력합니다.
4. 결과 리포트로 총/통과/실패 수와 실패 케이스 목록을 출력합니다.

## 11. 보너스: make_cross, make_x

```python
make_cross: 1 if (i == c or j == c) else 0     # c = n // 2, 가운데 행·열
make_x:     1 if (i == j or i + j == n - 1) else 0   # 두 대각선
```

3×3, 5×5, 13×13, 25×25 모두 홀수라 가운데 행·열이 하나로 정해집니다. 짝수 N이면 `n // 2`가 한쪽으로 치우치므로 십자가가 대칭이 아닙니다. `gen_sample.py`(제출 제외)가 테스트 데이터를 만들 때 이 함수를 재사용했습니다.

## 11-2. 보너스: 1차원 배열 최적화

```python
def flatten(m): ...            # N x N -> 길이 N*N 리스트 (행 우선)
def mac_flat(pf, ff):          # for a, b in zip(pf, ff): total += a * b
```

- 2차원 `mac`은 `pattern[i][j]`로 두 번 인덱싱하고 행마다 안쪽 루프를 새로 시작합니다. 1차원은 루프 하나에 `zip`으로 두 값을 바로 꺼냅니다.
- 곱셈·덧셈 횟수는 N²으로 같아서 시간 복잡도는 그대로 O(N²)이고, 상수 배만 줄어듭니다(측정 약 1.3~1.5배).
- `zip`을 쓴 순회도 값을 하나씩 처리하는 루프이므로 벡터화 연산이 아닙니다.
- 펼치는 비용은 패턴마다 한 번 듭니다. 그래서 표에 "펼침" 열을 따로 보여줍니다. `flat_comparison_table`이 결과 일치(`O/X`)까지 검사합니다.
- `measure_mac`에 `fn=mac` 인자를 추가해 같은 측정 함수로 두 버전을 공정하게 비교합니다.

## 12. main: 진입점

`input()`으로 모드를 받아 `1`이면 `mode_user_input`, `2`이면 `mode_json`을 호출하고, 그 외는 안내 메시지를 출력합니다. `if __name__ == "__main__":` 덕분에 `gen_sample.py`가 `from main import ...`를 해도 프로그램이 실행되지 않습니다.

## 13. 요구사항 ↔ 코드 대응표

| 요구사항 | 구현 위치 |
| --- | --- |
| 외부 라이브러리 금지 | import는 `json, os, re, time`뿐 |
| 이중 for문 MAC | `mac` |
| 라벨 정규화 | `normalize_label` |
| epsilon 동점 → UNDECIDED → FAIL | `judge_scores`, `evaluate_case` |
| 크기 불일치·스키마 오류도 비정상 종료 금지 | `validate_matrix`, `evaluate_case`의 try/except |
| 모드 1 오류 입력 시 재입력 | `read_matrix`의 while 루프 |
| 10회 반복 평균, I/O 제외 | `measure_mac` |
| 총/통과/실패와 실패 목록 | `mode_json` 마지막 블록 |

## 14. 직접 해보기 (이해 확인)

1. `EPSILON`을 `1e-9`에서 `1`로 키우면 어떤 케이스의 판정이 바뀌는지 예상한 뒤 실행해 보세요. (점수 차가 1 미만인 케이스가 UNDECIDED가 됩니다.)
2. `judge_scores`에서 동점 검사와 비교 검사의 순서를 바꾸면 `size_5_1`이 어떻게 되는지 확인해 보세요. (동점이 B=X로 판정되어 우연히 PASS가 되는 버그입니다.)
3. `data.json`의 `size_5_2` 입력 한 칸을 다른 크기 행으로 바꿔 `validate_matrix`가 어떤 사유를 출력하는지 보세요.
4. `mac`의 곱셈 부분에 `print(i, j, pattern[i][j] * filt[i][j])`를 임시로 넣어 누적 과정을 눈으로 확인해 보세요. (확인 후 지우세요. 측정 시간에 I/O가 섞입니다.)

## 15. 더 읽어볼 자료

- 새 라벨(패턴) 추가 방법: [README.md](README.md)의 "새 라벨(패턴) 확장 절차"
- 대규모 데이터 최적화: [README.md](README.md)의 "대규모 확장 시 최적화 전략"
