"""Mini NPU 시뮬레이터: MAC 연산으로 Cross / X 패턴을 판별한다. (표준 라이브러리만 사용)

구성: 핵심 연산 -> 검증 -> 모드 1/2 -> 보너스(패턴 생성기) -> 진입점
"""
import json
import os
import re
import sys
import time

# 두 점수의 차이가 이 값보다 작으면 동점으로 본다.
# (0.1, 0.9 같은 값은 부동소수점 오차가 있어 == 비교가 불안정하기 때문)
EPSILON = 1e-9
# 실행 위치(cwd)가 아니라 main.py가 있는 폴더 기준으로 data.json을 찾는다.
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")


# ---------- 핵심 연산 (print/input 없음: 시간 측정에 I/O가 섞이지 않게) ----------
def normalize_label(label):
    """'+'/'cross' -> 'Cross', 'x' -> 'X'. 알 수 없으면 ValueError."""
    # 공백·대소문자 차이를 흡수한 뒤 비교한다.
    key = str(label).strip().lower()
    if key in ("+", "cross"):
        return "Cross"
    if key == "x":
        return "X"
    # 오타를 조용히 넘기면 거짓 PASS가 생기므로 오류로 올린다.
    raise ValueError("알 수 없는 라벨: %r" % (label,))


def mac(pattern, filt):
    """위치별 곱셈 후 누적합 (이중 for문). N x N 이므로 O(N^2)."""
    total = 0.0
    for i in range(len(pattern)):  # 행
        for j in range(len(pattern[i])):  # 열
            # 같은 위치의 값끼리 곱해서 누적한다 (Multiply-Accumulate).
            total += pattern[i][j] * filt[i][j]
    return total


def judge_scores(score_a, score_b, name_a="A", name_b="B"):
    """epsilon 이내면 UNDECIDED, 아니면 점수가 큰 쪽의 이름을 반환."""
    # 동점 검사를 먼저 해야 한다. 순서가 반대면 동점이 항상 B로 판정된다.
    if abs(score_a - score_b) < EPSILON:
        return "UNDECIDED"
    return name_a if score_a > score_b else name_b


def measure_mac(pattern, filt, repeat=10, fn=mac):
    """I/O를 제외하고 MAC(fn)만 repeat회 반복한 평균 시간(ms)."""
    # perf_counter: 짧은 구간 측정용 고해상도 타이머
    start = time.perf_counter()
    for _ in range(repeat):
        fn(pattern, filt)
    # 총 시간 / 반복 횟수 = 평균(초), * 1000 = ms
    return (time.perf_counter() - start) / repeat * 1000.0


# ---------- 검증 (잘못된 데이터는 ValueError로 올려 FAIL 사유가 되게 함) ----------
def validate_matrix(m, size=None):
    """정사각 숫자 행렬인지 검사하고 N을 반환. size가 주어지면 크기도 확인."""
    if not isinstance(m, list) or not m:
        raise ValueError("2차원 배열이 아님")
    n = len(m)
    for row in m:
        # 각 행이 리스트이고 길이가 행 수와 같아야 정사각
        if not isinstance(row, list) or len(row) != n:
            raise ValueError("정사각 행렬이 아님 (행/열 수 불일치)")
        for v in row:
            # bool은 int의 하위 타입이라 따로 걸러낸다.
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ValueError("숫자가 아닌 값: %r" % (v,))
    if size is not None and n != size:
        raise ValueError("크기 불일치: %dx%d (기대 %dx%d)" % (n, n, size, size))
    return n


def load_filters(data):
    """{'size_N': {'cross'|'+': M, 'x': M}} -> {N: {'Cross': M, 'X': M}}"""
    result = {}
    raw = data.get("filters")
    if not isinstance(raw, dict):
        raise ValueError("'filters' 키가 없거나 형식 오류")
    for key, val in raw.items():
        # 키 형식 'size_숫자'만 허용하고 숫자 N을 추출
        m = re.fullmatch(r"size_(\d+)", key)
        if not m:
            raise ValueError("필터 키 형식 오류: %r" % key)
        size = int(m.group(1))
        if not isinstance(val, dict):
            raise ValueError("%s: 형식 오류" % key)
        # 필터 라벨을 내부 표기(Cross/X)로 통일
        fs = {}
        for lbl, mat in val.items():
            fs[normalize_label(lbl)] = mat
        if "Cross" not in fs or "X" not in fs:
            raise ValueError("%s: Cross/X 필터가 모두 필요" % key)
        # 필터의 실제 크기가 키의 N과 일치하는지 확인
        for mat in fs.values():
            validate_matrix(mat, size)
        result[size] = fs
    return result


def evaluate_case(name, case, filters):
    """케이스 하나 평가. 예외는 FAIL 사유로 변환한다(비정상 종료 금지)."""
    info = {"name": name, "pass": False, "reason": "", "scores": None, "judge": None}
    try:
        # 1) 패턴 키 'size_N_xxx'에서 N 추출
        m = re.fullmatch(r"size_(\d+)_.+", name)
        if not m:
            raise ValueError("패턴 키 형식 오류: %r" % name)
        size = int(m.group(1))
        # 2) 필수 키 확인 후 expected 정규화 (+ -> Cross, x -> X)
        if not isinstance(case, dict) or "input" not in case or "expected" not in case:
            raise ValueError("'input'/'expected' 키 누락")
        expected = normalize_label(case["expected"])
        # 3) 입력 패턴이 N x N 숫자 행렬인지 검증 (MAC 전에 걸러야 IndexError 방지)
        pattern = case["input"]
        validate_matrix(pattern, size)
        if size not in filters:
            raise ValueError("size_%d 필터 없음" % size)
        # 4) 두 필터에 대해 MAC 점수 계산 후 판정
        sc = mac(pattern, filters[size]["Cross"])
        sx = mac(pattern, filters[size]["X"])
        info["scores"] = (sc, sx)
        judged = judge_scores(sc, sx, "Cross", "X")
        info["judge"] = judged
        # 5) expected와 비교. UNDECIDED는 항상 FAIL
        if judged == "UNDECIDED":
            info["reason"] = "동점(|Cross-X| < %g) -> UNDECIDED, expected와 비교 시 FAIL" % EPSILON
        elif judged == expected:
            info["pass"] = True
        else:
            info["reason"] = "판정 %s != expected %s" % (judged, expected)
    except (ValueError, TypeError, KeyError) as e:
        # 어떤 검증 오류든 이 케이스만 FAIL로 기록하고 다음 케이스로 계속 진행
        info["reason"] = str(e)
    return info


# ---------- 모드 1: 사용자 입력 (3x3) ----------
def read_matrix(prompt, n=3):
    """n줄을 읽어 n x n 실수 행렬로 반환. 형식 오류면 안내 후 처음부터 재입력."""
    print(prompt + "  (첫 줄에 cross 또는 x 를 입력하면 자동 생성)")
    while True:
        rows = []
        try:
            for k in range(n):
                text = input().strip()
                if k == 0:
                    generated = generate_by_name(text, n)
                    if generated is not None:  # 생성기 재사용
                        print("자동 생성 (%s %dx%d):" % (text, n, n))
                        print_matrix(generated)
                        return generated
                line = text.split()
                if len(line) != n:  # 열 수 불일치
                    raise ValueError("각 줄은 %d개 숫자여야 합니다 (입력 %d개)" % (n, len(line)))
                rows.append([float(x) for x in line])  # 숫자 변환 실패도 ValueError
            return rows
        except ValueError as e:
            print("입력 오류: %s. 처음부터 다시 입력하세요." % e)


def mode_user_input():
    fa = read_matrix("필터 A (3줄, 공백 구분):")
    fb = read_matrix("필터 B (3줄, 공백 구분):")
    pt = read_matrix("패턴 (3줄, 공백 구분):")
    sa, sb = mac(pt, fa), mac(pt, fb)
    ms = measure_mac(pt, fa)  # 시간 측정은 입력이 끝난 뒤, MAC만 대상으로
    print("A 점수: %g / B 점수: %g / 연산 시간: %.4f ms" % (sa, sb, ms))
    res = judge_scores(sa, sb)
    print("판정: " + ("판정 불가 (UNDECIDED)" if res == "UNDECIDED" else res))


# ---------- 모드 2: data.json 분석 ----------
def performance_table(filters):
    """크기별 MAC 평균 시간(10회)과 연산 횟수(N^2) 표 출력."""
    print("\n=== 성능 분석 (10회 반복 평균) ===")
    print("%-8s %-18s %s" % ("크기", "평균 시간(ms)", "연산 횟수(N^2)"))
    for n in (3, 5, 13, 25):
        pat = make_x(n)  # 생성기로 만든 N x N X 패턴으로 측정
        # data.json에 해당 크기 필터가 없으면(예: 3x3) 생성기로 대체
        filt = filters.get(n, {}).get("Cross") or make_cross(n)
        print("%-8s %-18.4f %d" % ("%dx%d" % (n, n), measure_mac(pat, filt), n * n))


def mode_json(path=DATA_FILE):
    # 파일/스키마 오류는 메시지만 출력하고 정상 복귀 (JSONDecodeError는 ValueError 하위)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        filters = load_filters(data)
        patterns = data.get("patterns")
        if not isinstance(patterns, dict):
            raise ValueError("'patterns' 키가 없거나 형식 오류")
    except (OSError, ValueError) as e:
        print("data.json 로드 실패: %s" % e)
        return
    # 케이스별 평가 및 한 줄 출력
    results = []
    for name, case in patterns.items():
        r = evaluate_case(name, case, filters)
        results.append(r)
        sc = "" if r["scores"] is None else " Cross=%g X=%g 판정=%s" % (*r["scores"], r["judge"])
        print("[%s] %s%s %s" % ("PASS" if r["pass"] else "FAIL", name, sc, r["reason"]))
    performance_table(filters)
    flat_comparison_table()
    # 결과 리포트: 총/통과/실패 수와 실패 케이스 목록
    fails = [r for r in results if not r["pass"]]
    print("\n=== 결과 리포트 ===")
    print("총 %d / 통과 %d / 실패 %d" % (len(results), len(results) - len(fails), len(fails)))
    for r in fails:
        print(" - %s: %s" % (r["name"], r["reason"]))


# ---------- 보너스: 패턴 생성기 (홀수 N 기준) ----------
def make_cross(n):
    """가운데 행과 열이 1인 십자가 패턴. 짝수 N은 가운데 2줄을 모두 채워 대칭을 유지한다."""
    mids = {n // 2} if n % 2 else {n // 2 - 1, n // 2}
    return [[1 if (i in mids or j in mids) else 0 for j in range(n)] for i in range(n)]


def make_x(n):
    """두 대각선이 1인 X 패턴."""
    return [[1 if (i == j or i + j == n - 1) else 0 for j in range(n)] for i in range(n)]


# ---------- 보너스: 1차원 배열 최적화 ----------
def flatten(m):
    """N x N 2차원 리스트를 길이 N*N 1차원 리스트로 펼친다 (행 우선)."""
    flat = []
    for row in m:
        flat.extend(row)
    return flat


def mac_flat(pattern_flat, filter_flat):
    """1차원 버전 MAC. 인덱스 [i][j] 이중 접근과 안쪽 루프 설정이 사라진다.
    결과는 mac()과 같고 연산 횟수도 N^2으로 같다 (상수 배만 줄어듦)."""
    total = 0.0
    for a, b in zip(pattern_flat, filter_flat):
        total += a * b
    return total


def flat_comparison_table(repeat=100):
    """2차원 mac vs 1차원 mac_flat 전후 비교. 펼치는 비용은 따로 표시한다.
    필터는 한 번만 펼쳐 재사용하므로 '펼침 제외'가 반복 판정 시의 실제 비용이다."""
    print("\n=== 보너스: 1차원 배열 최적화 비교 (%d회 반복 평균) ===" % repeat)
    print("%-8s %-12s %-12s %-12s %-8s %s" % ("크기", "2차원(ms)", "1차원(ms)", "펼침(ms)", "배율", "결과 일치"))
    for n in (3, 5, 13, 25):
        pat = make_x(n)  # 생성기 재사용
        filt = make_cross(n)
        pf, ff = flatten(pat), flatten(filt)
        t2 = measure_mac(pat, filt, repeat)
        t1 = measure_mac(pf, ff, repeat, fn=mac_flat)
        # 펼치는 데 걸리는 시간 (패턴마다 한 번 필요)
        start = time.perf_counter()
        for _ in range(repeat):
            flatten(pat)
        tf = (time.perf_counter() - start) / repeat * 1000.0
        same = abs(mac(pat, filt) - mac_flat(pf, ff)) < EPSILON
        print("%-8s %-12.4f %-12.4f %-12.4f %-8s %s" % (
            "%dx%d" % (n, n), t2, t1, tf, "%.2fx" % (t2 / t1), "O" if same else "X"))


# ---------- 패턴 생성기: python3 main.py --gen [N] ----------
def generate_by_name(text, n):
    """'cross'/'+'/'x' 이름이면 n x n 생성 패턴을, 아니면 None을 반환 (모드 1에서 재사용)."""
    try:
        label = normalize_label(text)
    except ValueError:
        return None
    return make_cross(n) if label == "Cross" else make_x(n)


def print_matrix(m):
    """모드 1에 그대로 붙여넣을 수 있게 공백 구분 숫자로 출력."""
    for row in m:
        print(" ".join(str(v) for v in row))


def mode_generate(arg=None):
    """크기 N을 받아 N x N 십자가(Cross)와 X 패턴을 생성해 출력한다."""
    while True:
        text = arg if arg is not None else input("패턴 크기 N (3 이상의 정수): ")
        try:
            n = int(str(text).strip())
            if n < 3:
                raise ValueError
            break
        except ValueError:
            print("입력 오류: 3 이상의 정수를 입력하세요.")
            if arg is not None:  # 인자로 받은 값이 잘못되면 재입력 대신 종료
                return
    print("\n[Cross %dx%d]" % (n, n))
    print_matrix(make_cross(n))
    print("\n[X %dx%d]" % (n, n))
    print_matrix(make_x(n))


# ---------- 진입점 ----------
def main():
    # 패턴 생성기: python3 main.py --gen [N]
    if len(sys.argv) > 1 and sys.argv[1] in ("--gen", "-g"):
        mode_generate(sys.argv[2] if len(sys.argv) > 2 else None)
        return
    print("=== Mini NPU Simulator ===\n1. 사용자 입력 (3x3)\n2. data.json 분석")
    choice = input("모드 선택: ").strip()
    if choice == "1":
        mode_user_input()
    elif choice == "2":
        mode_json()
    else:
        print("1 또는 2를 입력하세요.")


# import 될 때(gen_sample.py 등)는 실행되지 않도록 보호
if __name__ == "__main__":
    main()
