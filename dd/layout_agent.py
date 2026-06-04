# -*- coding: utf-8 -*-
"""
다중 동선(여객/소방/BF) 가중치 최적화 내부 배치 에이전트 2D 테스트 코드
- 입력: test_data.json
- 단계: A* 동선 뼈대 → Optuna 방 배치 → 시각화 + 리포트
"""

import json
import heapq
import os
from collections import deque

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import optuna


# ----------------------------- 상수 정의 -----------------------------
FREE = 1
OBSTACLE = 0
PASSENGER = 2
FIRE = 3
BF = 4

CORRIDOR_KEYS = ['passenger', 'fire_evac', 'bf_barrier_free']
CORRIDOR_MARK = {'passenger': PASSENGER, 'fire_evac': FIRE, 'bf_barrier_free': BF}
CORRIDOR_COLOR = {
    'passenger': (0.55, 0.78, 1.00, 0.55),   # 연한 파랑
    'fire_evac': (1.00, 0.55, 0.55, 0.55),   # 연한 빨강
    'bf_barrier_free': (0.55, 0.95, 0.60, 0.55),  # 연한 녹색
}
COMMERCIAL_NAMES = {'편의점', '카페'}


# ----------------------------- 1단계: 데이터/Grid -----------------------------
def load_data(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def build_base_grid(data):
    W = data['project_boundary']['width']
    H = data['project_boundary']['height']
    grid = np.ones((H, W), dtype=np.int8)  # 1 = 이동 가능

    def mask_rect(rect):
        (x1, y1), (x2, y2) = rect
        x1c, x2c = max(0, x1), min(W, x2)
        y1c, y2c = max(0, y1), min(H, y2)
        grid[y1c:y2c, x1c:x2c] = OBSTACLE

    for obs in data.get('fixed_obstacles', []):
        mask_rect(obs['coords'])
    for room in data.get('locked_rooms', []):
        mask_rect(room['coords'])

    return grid, W, H


# ----------------------------- 2단계: A* + 통로 확장 -----------------------------
def astar(grid, start, goal):
    """4방향 A*. start/goal은 (x,y). 장애물이라도 start/goal은 통과 허용."""
    H, W = grid.shape
    sx, sy = start
    gx, gy = goal

    def h(x, y):
        return abs(x - gx) + abs(y - gy)

    def passable(x, y):
        if not (0 <= x < W and 0 <= y < H):
            return False
        if (x, y) == start or (x, y) == goal:
            return True
        return grid[y, x] != OBSTACLE

    open_heap = [(h(sx, sy), 0, (sx, sy))]
    came_from = {}
    g_score = {(sx, sy): 0}
    closed = set()

    while open_heap:
        f, gc, cur = heapq.heappop(open_heap)
        if cur in closed:
            continue
        if cur == (gx, gy):
            path = [cur]
            while cur in came_from:
                cur = came_from[cur]
                path.append(cur)
            return path[::-1]
        closed.add(cur)
        cx, cy = cur
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nx, ny = cx + dx, cy + dy
            if not passable(nx, ny):
                continue
            tentative = gc + 1
            if tentative < g_score.get((nx, ny), 10**18):
                g_score[(nx, ny)] = tentative
                came_from[(nx, ny)] = cur
                heapq.heappush(open_heap, (tentative + h(nx, ny), tentative, (nx, ny)))
    return None


def build_corridor_masks(grid_base, data):
    """각 동선마다 A* 경로 + width 확장으로 마스크 생성."""
    H, W = grid_base.shape
    masks = {}
    paths = {}
    for key in CORRIDOR_KEYS:
        spine = data['spine_networks'][key]
        nodes = spine['nodes']
        width = int(spine['width'])
        full_path = []
        for i in range(len(nodes) - 1):
            start = tuple(nodes[i]['coord'])
            goal = tuple(nodes[i + 1]['coord'])
            sub = astar(grid_base, start, goal)
            if sub is None:
                raise RuntimeError(f"[{key}] {start} -> {goal} 경로 없음")
            if i > 0:
                sub = sub[1:]
            full_path.extend(sub)
        paths[key] = full_path

        mask = np.zeros((H, W), dtype=bool)
        half = width // 2
        for (x, y) in full_path:
            x0, x1 = max(0, x - half), min(W, x + half + 1)
            y0, y1 = max(0, y - half), min(H, y + half + 1)
            # 장애물(기둥/벽/잠긴방)은 통로로 변환하지 않음
            mask[y0:y1, x0:x1] |= (grid_base[y0:y1, x0:x1] != OBSTACLE)
        masks[key] = mask
    return masks, paths


def build_combined_grid(grid_base, masks):
    """시각 디버깅용. 통로끼리 겹치는 경우 BF > Fire > Passenger 순으로 마킹."""
    g = grid_base.copy().astype(np.int8)
    g[masks['passenger']] = PASSENGER
    g[masks['fire_evac']] = FIRE
    g[masks['bf_barrier_free']] = BF
    return g


# ----------------------------- 거리 변환 -----------------------------
def distance_to_mask(mask):
    """Multi-source BFS로 각 셀에서 mask까지의 Manhattan 거리 계산."""
    H, W = mask.shape
    dist = np.full((H, W), np.inf, dtype=np.float32)
    dq = deque()
    ys, xs = np.where(mask)
    for y, x in zip(ys.tolist(), xs.tolist()):
        dist[y, x] = 0
        dq.append((x, y))
    while dq:
        x, y = dq.popleft()
        d = dist[y, x]
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < W and 0 <= ny < H and dist[ny, nx] > d + 1:
                dist[ny, nx] = d + 1
                dq.append((nx, ny))
    return dist


def perimeter_min_dist(x0, x1, y0, y1, dist_map):
    """방의 둘레(가장자리) 셀에서 dist_map의 최소값(=가장 가까운 출입구 위치 거리)."""
    if x1 <= x0 or y1 <= y0:
        return float('inf')
    top = dist_map[y0, x0:x1]
    bot = dist_map[y1 - 1, x0:x1]
    left = dist_map[y0:y1, x0]
    right = dist_map[y0:y1, x1 - 1]
    return float(min(top.min(), bot.min(), left.min(), right.min()))


# ----------------------------- 3단계: Optuna 최적화 -----------------------------
def room_dim_range(room, W, H):
    """방의 변 길이 (w,h) 후보 범위 계산."""
    ar = room['max_aspect_ratio']
    min_a, max_a = room['min_area'], room['max_area']
    side_min = max(2, int(np.floor(np.sqrt(min_a / ar))))
    side_max = int(np.ceil(np.sqrt(max_a * ar)))
    side_max = min(side_max, min(W, H) - 2)
    side_min = min(side_min, side_max)
    return side_min, side_max


def make_objective(ctx):
    rooms = ctx['rooms']
    W, H = ctx['W'], ctx['H']
    free_mask = ctx['free_mask']
    d_pass = ctx['dist_passenger']
    d_fire = ctx['dist_fire']
    d_bf = ctx['dist_bf']
    weights = ctx['weights']

    def objective(trial):
        occupancy = np.zeros((H, W), dtype=bool)
        placements = []

        overlap_pen = 0.0
        oob_pen = 0.0
        area_pen = 0.0
        aspect_pen = 0.0

        for i, room in enumerate(rooms):
            smin, smax = room_dim_range(room, W, H)
            rw = trial.suggest_int(f'w_{i}', smin, smax)
            rh = trial.suggest_int(f'h_{i}', smin, smax)
            cx = trial.suggest_int(f'cx_{i}', rw // 2 + 1, W - (rw - rw // 2) - 1)
            cy = trial.suggest_int(f'cy_{i}', rh // 2 + 1, H - (rh - rh // 2) - 1)

            x0 = cx - rw // 2
            y0 = cy - rh // 2
            x1 = x0 + rw
            y1 = y0 + rh

            # 경계 체크
            if x0 < 0 or y0 < 0 or x1 > W or y1 > H:
                oob_pen += 200000
                placements.append(None)
                continue

            # 장애물/통로 침범
            free_region = free_mask[y0:y1, x0:x1]
            invalid_cells = int((~free_region).sum())
            if invalid_cells > 0:
                overlap_pen += invalid_cells * 5000  # 치명적

            # 다른 방과 겹침
            occ_region = occupancy[y0:y1, x0:x1]
            if occ_region.any():
                overlap_pen += int(occ_region.sum()) * 5000
            occupancy[y0:y1, x0:x1] = True

            # 면적/비율
            area = rw * rh
            if area < room['min_area']:
                area_pen += (room['min_area'] - area) * 8
            elif area > room['max_area']:
                area_pen += (area - room['max_area']) * 4
            ar = max(rw / rh, rh / rw)
            if ar > room['max_aspect_ratio']:
                aspect_pen += (ar - room['max_aspect_ratio']) * 1500

            placements.append((x0, y0, x1, y1, room))

        # 동선별 점수
        passenger_score = 0.0
        fire_score = 0.0
        bf_score = 0.0

        for p in placements:
            if p is None:
                continue
            x0, y0, x1, y1, room = p
            x0c, x1c = max(0, x0), min(W, x1)
            y0c, y1c = max(0, y0), min(H, y1)
            if x1c <= x0c or y1c <= y0c:
                continue
            dp = perimeter_min_dist(x0c, x1c, y0c, y1c, d_pass)
            df = perimeter_min_dist(x0c, x1c, y0c, y1c, d_fire)
            db = perimeter_min_dist(x0c, x1c, y0c, y1c, d_bf)

            # 여객 동선: 상업시설(편의점/카페) ↔ 여객 통로 거리에 민감
            if room['name'] in COMMERCIAL_NAMES:
                passenger_score += (dp ** 2)

            # 소방 동선: 모든 방의 대피거리
            fire_score += (df ** 1.6)

            # BF 동선: 필수 방이 BF 통로와 인접해야 함 (거리 == 1이 이상)
            if room.get('requires_bf', False):
                if db <= 1:
                    bf_score += 0.0
                else:
                    bf_score += (db - 1) ** 2 * 40

        total = (
            passenger_score * weights['passenger_weight']
            + fire_score * weights['fire_evac_weight']
            + bf_score * weights['bf_weight']
            + area_pen + aspect_pen + overlap_pen + oob_pen
        )

        trial.set_user_attr('placements', [
            None if p is None else {
                'id': p[4]['id'], 'name': p[4]['name'],
                'x0': p[0], 'y0': p[1], 'x1': p[2], 'y1': p[3],
                'w': p[2] - p[0], 'h': p[3] - p[1],
                'area': (p[2] - p[0]) * (p[3] - p[1]),
            } for p in placements
        ])
        trial.set_user_attr('scores', {
            'passenger_raw': float(passenger_score),
            'fire_raw': float(fire_score),
            'bf_raw': float(bf_score),
            'passenger_weighted': float(passenger_score * weights['passenger_weight']),
            'fire_weighted': float(fire_score * weights['fire_evac_weight']),
            'bf_weighted': float(bf_score * weights['bf_weight']),
            'area_aspect_pen': float(area_pen + aspect_pen),
            'overlap_pen': float(overlap_pen + oob_pen),
        })
        return float(total)

    return objective


# ----------------------------- 4단계: 시각화 + 리포트 -----------------------------
def setup_korean_font():
    for name in ['Malgun Gothic', 'NanumGothic', 'AppleGothic', 'Noto Sans CJK KR']:
        try:
            plt.rcParams['font.family'] = name
            break
        except Exception:
            continue
    plt.rcParams['axes.unicode_minus'] = False


def visualize(data, grid_base, masks, placements, paths, save_path):
    H, W = grid_base.shape
    fig, ax = plt.subplots(figsize=(16, 10))
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.set_aspect('equal')

    # 배경 RGBA 이미지: 흰색 시작
    img = np.ones((H, W, 4), dtype=np.float32)

    # 장애물 (짙은 회색)
    obs = (grid_base == OBSTACLE)
    img[obs] = [0.28, 0.28, 0.28, 1.0]

    # 통로 (장애물 셀은 덮지 않음)
    for key in CORRIDOR_KEYS:
        m = masks[key] & ~obs
        c = np.array(CORRIDOR_COLOR[key], dtype=np.float32)
        alpha = c[3]
        img[m, :3] = alpha * c[:3] + (1.0 - alpha) * img[m, :3]

    ax.imshow(img, origin='lower', extent=[0, W, 0, H], interpolation='nearest')

    # 잠긴 방 라벨
    for r in data.get('locked_rooms', []):
        (x1, y1), (x2, y2) = r['coords']
        ax.text((x1 + x2) / 2, (y1 + y2) / 2, f"[고정]\n{r['name']}",
                ha='center', va='center', color='white', fontsize=9, fontweight='bold')

    # 고정 장애물 라벨
    for obs_item in data.get('fixed_obstacles', []):
        (x1, y1), (x2, y2) = obs_item['coords']
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        fontsize = 7 if obs_item['type'] == 'column' else 8
        ax.text(cx, cy, obs_item['name'],
                ha='center', va='center', color='#dddddd', fontsize=fontsize, fontweight='bold')

    # A* 경로 라인 (얇게)
    line_style = {'passenger': '-', 'fire_evac': '-', 'bf_barrier_free': '-'}
    edge_color = {'passenger': '#1f77b4', 'fire_evac': '#d62728', 'bf_barrier_free': '#2ca02c'}
    for key, pth in paths.items():
        if not pth:
            continue
        xs = [p[0] + 0.5 for p in pth]
        ys = [p[1] + 0.5 for p in pth]
        ax.plot(xs, ys, line_style[key], color=edge_color[key], linewidth=1.0, alpha=0.7)

    # spine_networks의 원본 노드 위치 및 이름 시각화
    for key, spine in data.get('spine_networks', {}).items():
        color = edge_color.get(key, 'black')
        for node in spine.get('nodes', []):
            x, y = node['coord']
            # 노드 마커 (동그라미) 그리기
            ax.plot(x, y, 'o', color=color, markersize=7, markeredgecolor='black', markeredgewidth=1.0, zorder=5)
            # 노드 이름 텍스트 그리기 (노드 바로 위에 말풍선 형태)
            ax.text(x, y + 1.2, node['name'], color='black', fontsize=7, fontweight='bold',
                    ha='center', va='bottom',
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=color, alpha=0.85, lw=0.8),
                    zorder=6)

    # 배치된 방
    for p in placements:
        if p is None:
            continue
        rect = Rectangle((p['x0'], p['y0']), p['w'], p['h'],
                         linewidth=1.6, edgecolor='black',
                         facecolor='#ffb066', alpha=0.55)
        ax.add_patch(rect)
        ax.text((p['x0'] + p['x1']) / 2, (p['y0'] + p['y1']) / 2,
                f"{p['name']}\n({p['w']}x{p['h']}={p['area']})",
                ha='center', va='center', fontsize=8, fontweight='bold')

    # 범례
    legend_items = [
        Rectangle((0, 0), 1, 1, facecolor=(0.28, 0.28, 0.28), label='장애물/고정방'),
        Rectangle((0, 0), 1, 1, facecolor=CORRIDOR_COLOR['passenger'][:3], alpha=0.6, label='여객 동선'),
        Rectangle((0, 0), 1, 1, facecolor=CORRIDOR_COLOR['fire_evac'][:3], alpha=0.6, label='소방 동선'),
        Rectangle((0, 0), 1, 1, facecolor=CORRIDOR_COLOR['bf_barrier_free'][:3], alpha=0.6, label='BF 동선'),
        Rectangle((0, 0), 1, 1, facecolor='#ffb066', alpha=0.55, label='배치된 방'),
    ]
    ax.legend(handles=legend_items, loc='upper right', framealpha=0.85)
    ax.set_title('내부 배치 에이전트 - 다중 동선 가중치 최적화 결과', fontsize=13)
    ax.grid(True, linestyle=':', alpha=0.25)
    plt.tight_layout()
    plt.savefig(save_path, dpi=130)
    print(f"[시각화] 저장 완료: {save_path}")
    plt.show()


def print_report(best_trial, weights):
    placements = best_trial.user_attrs.get('placements', [])
    scores = best_trial.user_attrs.get('scores', {})

    print("\n" + "=" * 72)
    print("           최종 평가 점수 리포트 (Best Trial)")
    print("=" * 72)
    print(f"총 페널티 (objective): {best_trial.value:,.2f}")
    print(f"가중치 적용 전 원점수:")
    print(f"  - Passenger_Score    : {scores.get('passenger_raw', 0):,.2f}")
    print(f"  - Fire_Score         : {scores.get('fire_raw', 0):,.2f}")
    print(f"  - BF_Score           : {scores.get('bf_raw', 0):,.2f}")
    print(f"가중치(passenger={weights['passenger_weight']}, "
          f"fire={weights['fire_evac_weight']}, bf={weights['bf_weight']}) 적용 후:")
    print(f"  - Passenger × w      : {scores.get('passenger_weighted', 0):,.2f}")
    print(f"  - Fire × w           : {scores.get('fire_weighted', 0):,.2f}")
    print(f"  - BF × w             : {scores.get('bf_weighted', 0):,.2f}")
    print(f"기타 페널티:")
    print(f"  - 면적/비율 페널티   : {scores.get('area_aspect_pen', 0):,.2f}")
    print(f"  - 충돌/경계 페널티   : {scores.get('overlap_pen', 0):,.2f}")

    print("\n--- 배치 좌표 JSON ---")
    print(json.dumps([p for p in placements if p is not None],
                     indent=2, ensure_ascii=False))
    print("=" * 72)


# ----------------------------- 메인 -----------------------------
def main():
    here = os.path.dirname(os.path.abspath(__file__))
    data_path = os.path.join(here, 'test_data.json')
    out_path = os.path.join(here, 'layout_result.png')

    setup_korean_font()
    data = load_data(data_path)

    # 1단계: Grid
    grid_base, W, H = build_base_grid(data)
    print(f"[1단계] Grid 생성: {W} x {H}, 장애물 셀 수 = {(grid_base == 0).sum()}")

    # 2단계: 다중 동선
    masks, paths = build_corridor_masks(grid_base, data)
    for k in CORRIDOR_KEYS:
        print(f"[2단계] {k:20s} 경로 길이={len(paths[k]):3d}, 통로 셀={int(masks[k].sum()):5d}")

    # 자유 셀(방 배치 가능) = FREE & 어떤 통로에도 속하지 않음
    free_mask = (grid_base == FREE)
    for m in masks.values():
        free_mask &= ~m

    # 거리 변환 (각 통로까지의 Manhattan 거리 맵)
    dist_passenger = distance_to_mask(masks['passenger'])
    dist_fire = distance_to_mask(masks['fire_evac'])
    dist_bf = distance_to_mask(masks['bf_barrier_free'])

    ctx = {
        'rooms': data['rooms_to_place'],
        'W': W, 'H': H,
        'free_mask': free_mask,
        'dist_passenger': dist_passenger,
        'dist_fire': dist_fire,
        'dist_bf': dist_bf,
        'weights': data['optimization_weights'],
    }

    # 3단계: Optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    sampler = optuna.samplers.TPESampler(seed=42)
    study = optuna.create_study(direction='minimize', sampler=sampler)
    print("[3단계] Optuna 최적화 시작 (n_trials=400)...")
    study.optimize(make_objective(ctx), n_trials=400, show_progress_bar=False)
    print(f"[3단계] 완료. best value = {study.best_value:,.2f}")

    # 4단계: 결과
    placements = study.best_trial.user_attrs.get('placements', [])
    visualize(data, grid_base, masks, placements, paths, out_path)
    print_report(study.best_trial, data['optimization_weights'])


if __name__ == '__main__':
    main()
