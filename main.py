"""Mini NPU 시뮬레이터: MAC 연산으로 Cross / X 패턴을 판별한다. (표준 라이브러리만 사용)"""
import json
import os
import re
import time

EPSILON = 1e-9
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")


# ---------- 핵심 연산 ----------
def normalize_label(label):
    """'+'/'cross' -> 'Cross', 'x' -> 'X'. 알 수 없으면 ValueError."""
    key = str(label).strip().lower()
    if key in ("+", "cross"):
        return "Cross"
    if key == "x":
        return "X"
    raise ValueError("알 수 없는 라벨: %r" % (label,))


def mac(pattern, filt):
    """위치별 곱셈 후 누적합 (이중 for문)."""
    total = 0.0
    for i in range(len(pattern)):
        for j in range(len(pattern[i])):
            total += pattern[i][j] * filt[i][j]
    return total


def judge_scores(score_a, score_b, name_a="A", name_b="B"):
    """epsilon 이내면 UNDECIDED."""
    if abs(score_a - score_b) < EPSILON:
        return "UNDECIDED"
    return name_a if score_a > score_b else name_b


def measure_mac(pattern, filt, repeat=10):
    """I/O 제외, MAC만 repeat회 반복한 평균 시간(ms)."""
    start = time.perf_counter()
    for _ in range(repeat):
        mac(pattern, filt)
    return (time.perf_counter() - start) / repeat * 1000.0


# ---------- 검증 ----------
def validate_matrix(m, size=None):
    """정사각 숫자 행렬인지 검사하고 N을 반환."""
    if not isinstance(m, list) or not m:
        raise ValueError("2차원 배열이 아님")
    n = len(m)
    for row in m:
        if not isinstance(row, list) or len(row) != n:
            raise ValueError("정사각 행렬이 아님 (행/열 수 불일치)")
        for v in row:
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
        m = re.fullmatch(r"size_(\d+)", key)
        if not m:
            raise ValueError("필터 키 형식 오류: %r" % key)
        size = int(m.group(1))
        if not isinstance(val, dict):
            raise ValueError("%s: 형식 오류" % key)
        fs = {}
        for lbl, mat in val.items():
            fs[normalize_label(lbl)] = mat
        if "Cross" not in fs or "X" not in fs:
            raise ValueError("%s: Cross/X 필터가 모두 필요" % key)
        for mat in fs.values():
            validate_matrix(mat, size)
        result[size] = fs
    return result


def evaluate_case(name, case, filters):
    """케이스 하나 평가. 예외는 FAIL 사유로 변환(비정상 종료 금지)."""
    info = {"name": name, "pass": False, "reason": "", "scores": None, "judge": None}
    try:
        m = re.fullmatch(r"size_(\d+)_.+", name)
        if not m:
            raise ValueError("패턴 키 형식 오류: %r" % name)
        size = int(m.group(1))
        if not isinstance(case, dict) or "input" not in case or "expected" not in case:
            raise ValueError("'input'/'expected' 키 누락")
        expected = normalize_label(case["expected"])
        pattern = case["input"]
        validate_matrix(pattern, size)
        if size not in filters:
            raise ValueError("size_%d 필터 없음" % size)
        sc = mac(pattern, filters[size]["Cross"])
        sx = mac(pattern, filters[size]["X"])
        info["scores"] = (sc, sx)
        judged = judge_scores(sc, sx, "Cross", "X")
        info["judge"] = judged
        if judged == "UNDECIDED":
            info["reason"] = "동점(|Cross-X| < %g) -> UNDECIDED, expected와 비교 시 FAIL" % EPSILON
        elif judged == expected:
            info["pass"] = True
        else:
            info["reason"] = "판정 %s != expected %s" % (judged, expected)
    except (ValueError, TypeError, KeyError) as e:
        info["reason"] = str(e)
    return info


# ---------- 모드 1 ----------
def read_matrix(prompt, n=3):
    print(prompt)
    while True:
        rows = []
        try:
            for _ in range(n):
                line = input().split()
                if len(line) != n:
                    raise ValueError("각 줄은 %d개 숫자여야 합니다 (입력 %d개)" % (n, len(line)))
                rows.append([float(x) for x in line])
            return rows
        except ValueError as e:
            print("입력 오류: %s. 처음부터 다시 입력하세요." % e)


def mode_user_input():
    fa = read_matrix("필터 A (3줄, 공백 구분):")
    fb = read_matrix("필터 B (3줄, 공백 구분):")
    pt = read_matrix("패턴 (3줄, 공백 구분):")
    sa, sb = mac(pt, fa), mac(pt, fb)
    ms = measure_mac(pt, fa)
    print("A 점수: %g / B 점수: %g / 연산 시간: %.4f ms" % (sa, sb, ms))
    res = judge_scores(sa, sb)
    print("판정: " + ("판정 불가 (UNDECIDED)" if res == "UNDECIDED" else res))


# ---------- 모드 2 ----------
def performance_table(filters):
    print("\n=== 성능 분석 (10회 반복 평균) ===")
    print("%-8s %-18s %s" % ("크기", "평균 시간(ms)", "연산 횟수(N^2)"))
    for n in (3, 5, 13, 25):
        pat = [[1.0] * n for _ in range(n)]
        filt = filters.get(n, {}).get("Cross") or make_cross(n)
        print("%-8s %-18.4f %d" % ("%dx%d" % (n, n), measure_mac(pat, filt), n * n))


def mode_json(path=DATA_FILE):
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
    results = []
    for name, case in patterns.items():
        r = evaluate_case(name, case, filters)
        results.append(r)
        sc = "" if r["scores"] is None else " Cross=%g X=%g 판정=%s" % (*r["scores"], r["judge"])
        print("[%s] %s%s %s" % ("PASS" if r["pass"] else "FAIL", name, sc, r["reason"]))
    performance_table(filters)
    fails = [r for r in results if not r["pass"]]
    print("\n=== 결과 리포트 ===")
    print("총 %d / 통과 %d / 실패 %d" % (len(results), len(results) - len(fails), len(fails)))
    for r in fails:
        print(" - %s: %s" % (r["name"], r["reason"]))


# ---------- 보너스: 패턴 생성기 ----------
def make_cross(n):
    c = n // 2
    return [[1 if (i == c or j == c) else 0 for j in range(n)] for i in range(n)]


def make_x(n):
    return [[1 if (i == j or i + j == n - 1) else 0 for j in range(n)] for i in range(n)]


def main():
    print("=== Mini NPU Simulator ===\n1. 사용자 입력 (3x3)\n2. data.json 분석")
    choice = input("모드 선택: ").strip()
    if choice == "1":
        mode_user_input()
    elif choice == "2":
        mode_json()
    else:
        print("1 또는 2를 입력하세요.")


if __name__ == "__main__":
    main()
