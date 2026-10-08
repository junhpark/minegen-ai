# MineGen-AI — 1차 수동 수락 후속 계획 (Hardening, 2-PR 속도 모드)

- 기준: `junhpark/minegen-ai` main `62faf93` (2026-10-04, PR #52 머지, Phase 23C까지 완료)
- 입력: 2026-10-06 수동 수락 결과 18개 항목 + 2차 검증의견(H0–H4 제안) + 그에 대한 평가
- 성격: **실행 계획서이자 Claude Code 지시문의 원본.** 코드·문서·규칙은 아직 바꾸지 않았다.
- 권장 위치: 리포지토리 `docs/hardening-plan.md` (PR-1 첫 커밋에 포함). Claude Code 지시는 "docs/hardening-plan.md §2를 읽고 PR-1을 수행하라"처럼 절 번호로 가리킨다.
- 변경 요지: **중간 수동 수락 없음, PR 2개, 결정 필요 항목은 전부 여기서 확정.**

> 읽지 못한 것: 지정된 YouTube 영상(M9A_Gybcf3U)은 확인하지 못했다. Cut & Fill 기본값은 SME Mining Reference Handbook 10장과 Hard Rock Miner's Handbook §3 근거로 확정했다(§6). 모든 값이 명시적 파라미터이므로 영상 근거로 나중에 기본값만 바꾸면 된다.

---

## 0. 실행 방식

### 0.1 원칙

1. **수동 수락은 마지막에 한 번.** 그 대신 각 PR은 자동 e2e(Playwright, `e2e` 마커)로 Setup→Export 전체 흐름을 BASELINE 시나리오에서 통과시킨다. 이것이 중간 수락의 대체물이다.
2. **PR 2개.** PR-1 = 정확성 + 워크플로 셸, PR-2 = 엔진 + 분석 + 데모. 각 PR 안에서는 커밋을 작업 패키지(H0–H4) 단위로 나누고, 커밋마다 FAST, PR 닫을 때 FULL(rule 181).
3. **rule 126 그대로.** 로컬 커밋은 자유, push/PR/merge는 Park의 건별 승인. PR당 승인 2회(push, merge)이므로 총 4회.
4. **폴백 하나만.** PR-2의 FULL 종료가 막히면(세션 컨텍스트 소진 또는 골든 비교 미해결) §5의 커밋 4/5 경계에서 PR-2a(엔진)/PR-2b(분석·데모)로 쪼갠다. 그 외 분할 없음.
5. **결정은 이 문서가 한다.** §10의 기본값은 전부 명시적 파라미터로 들어가므로 수락 후 바꾸는 비용은 한 줄이다.

### 0.2 작업 패키지와 PR 매핑

| 패키지 | 내용 | PR |
|---|---|---|
| H0 정확성 | TABULAR Level Development, Walkthrough Go To, ⓘ 팝오버, 분기점 검은 판 진단 | PR-1 |
| H1 셸 | 리본·스테퍼·3분할·상태줄, Setup(Scenario+Method), Reset(백엔드 단일 authority), Export 이동, View 패널, Option n 표기 | PR-1 |
| H2 엔진 | Cut & Fill 두 축 + 패널 + sill mat, MineExchange 1.3.1 additive, Shaft mesh + 스펙 편집기 | PR-2 |
| H3 4D·분석 | timeseries 프로젝션, 4D 반복·우측 그래프, 전체창 Analysis, Planning IRR, 민감도, 공정 what-if | PR-2 |
| H4 데모 | 사전 생성 데모 3개, Demos 메뉴, 데모 모드(viewer-only·auto tour·4D loop) | PR-2 |

HF Space 배포(D0)는 두 PR 머지와 최종 수락 뒤 별도.

### 0.3 2차 검증의견 반영 결과

| 리뷰어 제안 | 판정 | 근거 |
|---|---|---|
| H0–H4 명칭, Phase 24 번호 미사용 | 수용 | 출처는 `H2-CF (21B/C hardening)`식으로만 기록 |
| Reset authority는 backend 하나 | 수용 + 보정 | preview와 실행 DELETE가 **같은** `artifact_registry.invalidated_by()` 출력을 반환. 프런트 `invalidation.ts` 미러 폐기(§4.4) |
| Method 변경 시 World 유지 | **반대** | rule 40/119/151 + world commit record와 충돌하는 아키텍처 변경인데, World는 같은 seed의 순수 함수라 재생성 비용이 작다. UX 문구만 "Layout 이후 초기화"로(§4.3) |
| L01 제외 + "coverage 불변" 증명 | **대체** | L01 제외는 L01–L02 구간 손실이 정의상 따라온다(rule 76/195). 수락 기준을 legacy↔layout-v2 parity + 명시적 unserved 보고 + typed 힌트로(§3.1) |
| C&F 두 축 분리 | 수용 + **보정** | 축은 독립이 아니다. OVERHAND+SHALLOW_TO_DEEP는 cemented sill mat 없이 성립하지 않는다(§6.3). UNDERHAND는 typed UNSUPPORTED |
| maxConcurrentPanels 등 명시 | 수용 | registry canonical default(rule 194 방식), UI 노출 |
| MineExchange 1.4 유예 | 수용 (조건) | 새 파라미터를 exporter가 조용히 빠뜨리는 상태는 불가 → 1.3.1 additive patch(§6.6) |
| Shaft mesh 포함 | 수용 | `ShaftLayer.tsx`는 `<line>`만, `development_mesh.py:81 KIND_ORDER`에 shaft 없음 — 실제로 빠져 있었다 |
| hostRockDensity 2.7 silent default 금지 | 수용 | `scenario.geology.hostRockDensity` optional, 없으면 m³만 |
| Planning IRR·gross-revenue 민감도 먼저, 금속가격은 별도 | 수용 | IRR 비존재는 typed(§8.3) |
| Demo=H4, HF=D0 | 수용 | |
| 단계별 수동 수락 | **폐기(Park 결정)** | 자동 e2e로 대체, 수락은 마지막 한 번 |

---

## 1. 수락 항목 → 원인 → 패키지

| # | 지적 | 코드 사실 | 패키지 |
|---|---|---|---|
| 1 | UI가 시원하지 않고 이해가 어렵다 | 좌측 320 px 패널에 Scenario·Export·탭·카드·Layers가 세로로 쌓임. 스테퍼 없음(`PanelTabs.tsx`). `nextActionVariant`가 카드마다 독립이라 주 버튼이 동시에 여러 개 | H1 |
| 2 | 중간 단계 초기화 | 삭제·리셋 엔드포인트 없음(DELETE는 `api/results.py:131` 하나). 캐스케이드는 `DesignService._invalidate_downstream(scenario_id, *written, source)`(`design_service.py:334-336`)가 쓰기 직후에만 호출 | H1 |
| 3 | 시나리오 선택 → Generate World 순서 혼동 | `ScenarioPanel.tsx`: Generate world(:188)가 New scenario 폼(:208) 위, 'New synthetic mine'은 회색 | H1 |
| 4 | Export가 맨 앞 | `ScenarioPanel.tsx:328-373` 항상 펼쳐진 채 탭 위 | H1 |
| 5 | ⓘ 설명 잘림 | `InfoPopover.tsx:64` `absolute top-5 right-0 w-56`, 클램프·플립 없음. `<aside>` `overflow-y-auto` | H0 |
| 6 | 대표 데모 1–2개 | 사전 생성 시나리오 없음 | H4 |
| 7 | 텍스트 과다, 컨트롤 좌·진행 우 | 우측 패널이 모든 모드에서 `InspectorPanel`. 상태·지표·실패 사유가 전부 좌측 카드 안 | H1 |
| 8 | TABULAR Level Development 실패 | **재현.** `levels/builder.py:500-508` 해석적 교점이 무한 footwall 평면과의 교점이라 `v` 범위 미검사. L01 고도 `z_max − top_margin`은 hanging-wall 상단 기준이라 footwall 상단보다 `T·cos(dip)` 높음. seed 42: 11.87 m > 10 m → sdf 2.1206 m(UI 2.121e+00). legacy는 `targets.py:199` `OUTSIDE_OREBODY_DIP_EXTENT`로 typed-reject, layout-v2 앵커(`layout/access.py:387-426`)는 `sec.empty`만 본다 | H0 |
| 9 | 4D 반복 재생 | `timelineStore.ts:8-23` loop 없음. `TimelineControl.tsx:44-48` 끝에서 clamp+pause | H3 |
| 10 | Layers → 뷰 전용 패널 | `LayerPanel`이 좌측 aside 마지막에 접힌 채 | H1 |
| 11 | Go To 사라짐, 분기점 안 보임 | `teleport.ts:25-48` 대상 = network SUCCESS의 `LEVEL_ENTRY` 중 램프 중심선 15 m 이내만. Layout v2 진입점은 분기점에서 ≥ 6×폭(30 m) → 목록이 Portal만 남거나 levels 실패→network null→드롭다운 숨김(`WalkthroughHUD.tsx:68-88`). `RAMP_JUNCTION` 후보 없음 | H0 |
| 12 | 4D 우측 비용·채굴량 그래프 | 4D 전용 패널·수량 시계열 API 없음 | H3 |
| 13 | Analysis 전체창, cashflow 너무 작음 | `App.tsx:32` 캔버스 무조건. `CashflowTable.tsx:55-85` 48 px SVG | H3 |
| 14 | 후보 이름 1,2,3 | `LayoutComparisonPanel.tsx:30-34` 파라미터 id를 잘라 표시. id는 식별자(rule 142) → **표시만** 변경 | H1 |
| 15 | 민감도·NPV·IRR·기간 | `EconomicsConfig` 11필드, 수익 = `tonnes × gross_revenue_per_mined_tonne`. IRR·민감도는 rule 199/201이 명시 배제 → 규칙 개정 | H3 |
| 16 | Mining method 위치·시퀀스 | 마지막 탭. 적용 = scenario PUT + world 재생성, 확인창 없음(`DesignPanel.tsx:866-874`). `sublevel_interval`이 레벨 고도→램프 패밀리에 영향 → **Layout보다 앞** | H1 |
| 17 | Shaft 언제 보이나 | `specs=[]` 기본, 편집 UI 없음(`DesignPanel.tsx:646-660`), 한 station 실패 = 샤프트 전체 실패(`shafts/planner.py:420-426`), mesh 없음 | H2 |
| 18 | Cut & Fill 시퀀스 오류 | `cut_fill.py:137` 구간 하→상, `:146` 리프트 하→상, `:165` 전역 스네이크, `:301-370` `prep_deps = {access_task} ∪ {previous_cure}` → 광산 전체 단일 체인. 첫 PREP은 램프가 최심부 분기점에 닿아야(`scheduling/builder.py:313-333`). 블록·패널·필러·동시성 없음 | H2 |

---

## 2. PR-1 지시문 헤더

```text
branch: hardening-1-shell
scope: H0 (정확성 4건) + H1 (가이드형 워크플로 셸, Reset, Setup, View 패널, Option n)
비범위: 엔진 DTO·artifact 변경(Reset 엔드포인트 제외), C&F, Shaft, 4D 그래프, Analysis 대시보드, 데모
커밋 순서: §3.1 → §3.2 → §3.3 → §4.4(reset backend) → §4.1–4.3(shell) → §3.4(검은 판 진단) → 규칙·문서
게이트: 커밋마다 scripts/verify.py fast; PR 종료 시 full; frontend 4종; e2e: BASELINE Setup→Export
골든: legacy 22케이스 불변, layout-v2 FULL_SUITE byte-identical, parity 192/193 불변
규칙: 141 확장, 191 → 신규 규칙으로 대체, 신규 Reset 규칙, 신규 Go To 규칙
rule 126 보고 후 push 승인 요청
```

## 3. H0 — 정확성

### 3.1 TABULAR 최상위 레벨 (항목 8)

**재현값**: RANDOM_TABULAR seed 42 → dip 61.594°, 두께 24.942 m. L01 접촉점 `v` = −191.098 vs `half_height` 188.978. `|sdf| = (T·cos(dip) − top_margin)/sin(dip)` = 2.1206 m. L02–L13은 1e-14. `fail()`(`:420-423`)이 첫 사유만 남겨 S-05 하나로 보이지만 L01의 11개 station 전부 같은 값. C&F·R&P도 같은 루프.

**센서스(읽기 전용)**: TABULAR 21케이스 중 overshoot > 0은 `RANDOM_TABULAR-101`(2.82 m, 1/7 레벨), `-105`(7.14 m, 1/9), `-106`(1.68 m, 1/11). layout-v2 FULL_SUITE TABULAR는 0건. legacy 22케이스는 가드가 이미 있어 불변.

**수정**: 레벨 고도 생성(rule 141 단일 정의)은 건드리지 않는다. layout-v2 TABULAR 앵커의 서비스 가능성 판정에 legacy와 같은 가드를 더한다 — `|footwall_contact_v_coord(ob, z)| > half_height`인 레벨은 typed 제외 `NO_FOOTWALL_CONTACT_AT_LEVEL`(rule 141의 `NO_OREBODY_SECTION_AT_LEVEL` 선례). L01은 required set에서 빠지고 램프는 L02부터 서비스.

**보고(필수)**: `levels.json`에 `excludedLevels[] {levelId, elevation, reason, overshootM}` 와 `unservedIntervals[] {upperLevelId, lowerLevelId, reason}`. UI 레벨 단계와 Analysis Overview에 "Top level L01 excluded — footwall contact above orebody top (2.12 m). Minimum topMiningMargin for L01: 11.87 m" 형태로 표시. 힌트 값은 TABULAR 해석식 `T·cos(dip)` (dip-aware, 다른 광체형은 힌트 없음).

**수락(자동)**: (a) seed 42 재현 케이스 levels SUCCESS(12 레벨, L01 excluded); (b) RANDOM_TABULAR 골든 12건에서 layout-v2 serviceable 레벨 집합 == legacy targets의 유효 레벨 집합(parity 테스트 신설); (c) layout-v2 골든 4건 byte-identical; (d) legacy 골든·parity 192/193 불변.

**비범위·후속**: `topMarginReference = HANGING_WALL_TOP(현행) | FOOTWALL_TOP` 옵션(모든 경사 TABULAR의 레벨 고도를 바꿔 골든 계약 변경)은 이번 PR에 넣지 않는다. 최종 수락 후 별도 항목.

### 3.2 Walkthrough Go To (항목 11)

대상을 `RAMP_JUNCTION` 노드(`chainage` 보유, 램프 위에 정확히 존재)로 바꾸고 15 m 근접 판정을 버린다. network가 없을 때는 `level_accesses.json`의 junction chainage → 없으면 Effective Ramp 세그먼트 경계(rule 155: 세그먼트는 분기점에서 끊김)로 폴백해 **levels 실패와 무관하게** Portal + L01…Lnn turnout 목록을 만든다. authority는 `RAMP_JUNCTION.chainage`. LEVEL_ENTRY로의 branch teleport는 별도(20D.x).

수락(자동): levels FAILED 시나리오에서도 Portal + turnout 목록·이동. `teleport.test.ts`에 Layout v2 픽스처(진입점 30 m 이격) 추가.

### 3.3 ⓘ 팝오버 (항목 5)

`InfoPopover`를 `createPortal`로 body에, 앵커 `getBoundingClientRect` 기준 위치, 좌우 플립 + 뷰포트 클램프. 클릭 열기 유지(hover-only 금지). H1 셸 커밋보다 먼저 독립 커밋으로 넣고 셸이 그 컴포넌트를 쓴다.

### 3.4 분기점 검은 판 (스크린샷 2)

가설: levels FAILED라 development mesh가 ACCESS-ONLY(`13 access · 0 drift`)였고, 접근 튜브가 진입점에서 OPEN 끝으로 끝나 내부 셸(뒷면)이 램프 안쪽에서 보인 것(rule 166의 기록된 한계와 같은 현상). §3.1 적용 후 같은 시나리오로 재확인 → 사라지면 종료. 남으면 해당 분기점의 `report.junctions`(opened/removed/clipped)를 캡처해 **typed finding으로 기록하고 PR-2 H2-SH 커밋 전에 처리**(원인이 junction cut 결함이면 거기서, 재질/조명이면 프런트 한 줄). 헤드램프 강도·aperture 림 재질은 프런트 전용으로 보완.

---

## 4. H1 — 가이드형 워크플로 셸

### 4.1 설계 원칙

- **순서가 화면이다.** 어디까지 왔고 다음이 무엇인지 한 곳에서 보이고, 주 버튼은 화면에 하나만 켜진다.
- **컨트롤과 결과를 분리한다.** 좌 = 현재 단계의 파라미터·행동. 우 = 전 단계 상태·핵심 지표·`failureReason`·Details. 하 = 상태줄·작업 진행·4D 컨트롤.
- **3D | 4D | Walk는 워크플로 단계가 아니라 뷰 모드다.** Analysis는 뷰가 아니라 전체창 작업대(PR-2). 지금 상단의 `DESIGN | SYSTEMS | 4D | WALKTHROUGH | ANALYSIS`가 서로 다른 종류를 한 줄에 두고 있는 것이 혼동의 큰 원인.
- rule 191의 원칙(상태·지표·`failureReason` 항상 노출, 단계/규칙 번호 비노출, `StatusBadge`는 백엔드 status의 presentation mapping, 탭 전환은 presentation event)은 승계하고 "좌측 패널 구조" 조항만 새 규칙으로 대체한다.

### 4.2 화면 구조

```text
┌ File ▾ │ 1 Setup · 2 Design · 3 Network · 4 Mining · 5 Systems · 6 Analysis · 7 Export ┐
│ [Scenario ✓][Method ✓][Layout ●][Levels ○][Excavation ○][Shafts –] …                   │ ← 스테퍼: ✓완료 ●다음 ○대기 ✗실패 ↻stale –선택
├──────────────┬──────────────────────────────────┬────────────────────────────────────────┤
│ CONTROLS     │                                  │ STATUS & RESULTS                       │
│ 현재 단계     │   3D / 4D / Walk  (뷰 전환기)     │ 단계별 상태 · 핵심 지표 · failureReason │
│ [주 행동 1개] │                                  │ Details ▸                              │
│ [Reset from  │                                  ├────────────────────────────────────────┤
│  here]       │                                  │ VIEW: layers 트리 · slice · 카메라 프리셋│
├──────────────┴──────────────────────────────────┴────────────────────────────────────────┤
│ 상태줄: World · Ramp · Levels · Network · Timeline 칩 │ 작업 진행률 │ 4D 컨트롤           │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

- **File 메뉴**: New / Open(saved) / Demos(PR-2) / Export(MineExchange·Ventsim·AnyLogic·Unity·Unreal) / Import results. Export는 리본 7단계에도 있다(두 경로, 한 구현).
- **VIEW 패널**(RS3 Visibility 트리): World › Terrain/Orebody/Faults/Slice, Design › Ramp/Access/Levels/Meshes/Shafts, Network, Production, Systems, Results. 순수 프런트, 뷰어 로컬.

### 4.3 단계 시퀀스

| 단계 | 하위 | 주 행동 | 비고 |
|---|---|---|---|
| 1 Setup | Scenario | **Create mine**(생성 + world 생성 한 번에) | Randomize는 보조. Saved/Demo는 File |
| | Method | 채광법 + 파라미터(`sublevelInterval`, 메서드별) 확정 | **World 생성 전에 결정** → 재생성 불필요. 나중에 바꾸면 scenario PUT = 전체 초기화. 확인창 문구: "World는 같은 seed로 재생성되고 Layout 이후가 초기화됩니다"(reset-plan 응답 그대로 나열) |
| 2 Design | Layout | Generate → **Option n** 선택 → Activate | 라벨은 순위순 "Option 1…n", id·패밀리·파라미터는 Details(rule 142 불변) |
| | Levels | Generate | 제외 레벨·unserved 구간 표시(§3.1) |
| | Excavation | Generate | ramp mesh + development mesh |
| | Shafts(선택) | Plan | 편집기는 PR-2 |
| 3 Network | Network, Capability | Generate | |
| 4 Mining | Production, Schedule | Generate | Method는 1단계로 이동 |
| 5 Systems | Communication, Sensors | Generate | |
| 6 Analysis | 전체창 | — | PR-2; PR-1에서는 현 Analysis 패널을 전체창 자리에 임시 배치 |
| 7 Export | 번들/어댑터 | Export | |

### 4.4 Reset — backend 단일 authority

```text
backend artifact registry (invalidated_by)
        ↓
GET  …/design/reset-plan?from=<artifact>      → { from, willDelete: [...] }     (읽기 전용 프로젝션)
        ↓
frontend 확인창: willDelete 나열 (프런트는 표시만)
        ↓
DELETE …/design/{artifact}                    → { deleted: [...] }              (같은 클로저)
        ↓
frontend: 응답 deleted[]로 scene 슬롯 비움 (새 클로저 없음)
```

- 스테이지→artifact 매핑은 백엔드 한 곳(`services/workflow_stages.py` 또는 registry 옆). 프런트는 stage id만 보낸다.
- 삭제는 저장소 락 안에서 해당 파일 + 클로저. STALE/MALFORMED도 삭제 가능(복구 수단). `ramp_source.json`은 루트라 건드리지 않음(rule 162). 없으면 404 `*_NOT_GENERATED`.
- 프런트 `invalidation.ts`에 새 미러 클로저를 **추가하지 않는다.** 기존 `afterLayoutSelect`/`afterRampSourceChange`(rule 169)는 그대로.
- Method 변경은 scenario PUT이므로 reset-plan이 아니라 rule 40 전체 초기화 경로. 확인창만 §4.3 문구.
- 규칙 초안: "초기화는 레지스트리 클로저의 삭제이며, preview와 실행은 같은 함수의 출력이고, 프런트는 의존 그래프를 갖지 않는다."

### 4.5 수락(자동 e2e)

BASELINE 시나리오에서 Setup(Create mine → Method) → Layout(Option 1 Activate) → Levels → Excavation → Network → Mining → Systems → Export(MineExchange 다운로드) 한 흐름이 통과한다. 어느 단계에서든 Reset from here 뒤 그 단계부터 재생성된다. 주 버튼이 동시에 둘 이상 켜지지 않는다(DOM 단언).

---

## 5. PR-2 지시문 헤더

```text
branch: hardening-2-engine-analysis
scope: H2 (Cut & Fill 두 축·패널·sill mat, MineExchange 1.3.1, Shaft mesh + 편집기)
       + H3 (timeseries, 4D loop·그래프, 전체창 Analysis, Planning IRR, 민감도, 공정 what-if)
       + H4 (데모 3개, Demos 메뉴, 데모 모드)
커밋 순서: 1 C&F 스키마·기하 → 2 C&F 스케줄 → 3 MineExchange 1.3.1 + 어댑터 → 4 Shaft mesh·편집기
          → 5 timeseries + hostRockDensity + 4D loop·그래프(recharts 도입) → 6 Analysis 전체창·IRR·민감도·what-if
          → 7 데모 → 8 규칙·문서
폴백 분할점: 커밋 4 | 5
게이트: 커밋마다 fast, 종료 full, frontend 4종, e2e: BASELINE + CUT_AND_FILL 데모 Setup→Analysis→Export
골든: 롱홀 baseline(phase21bc) byte-identical(BLOCKING), 22케이스·layout-v2 불변; C&F 픽스처는 의도적 재생성 + 비교 문서
규칙: 182·195·196·201 개정, 신규 timeseries/민감도/데모 규칙
```

### 5.1 PR-2 구현 기록 (hardening-2-engine-analysis, base main `1bd68c8`)

| 커밋 | 내용 | 계획 대비 결정 |
|---|---|---|
| C1 `926d07b` | C&F 스키마·기하: 두 축, 패널·블록, rib pillar, cemented sill mat, `sequencing`/`blocks`/`panels` payload, integrity | §6.3 그대로. UNDERHAND는 생성·스케줄 모두 typed 거부 |
| C2 `98496cf` | 패널 선행관계 스케줄, `maxConcurrentPanels` 상한, sill-mat 양생 게이트 | 특성화 기록 `docs/findings/h2cf-cut-fill-characterization.md`(첫 STOPING 404.45→298.18 d, 램프 완료 371.46 d) |
| C3 `8165a86` | MineExchange 1.3.1 additive, AnyLogic `cemented` 열 | 어댑터 버전 불변(1.3.x 수용) |
| C4 `9ea688d` | `shaft_mesh.{json,glb}` leaf artifact, ShaftSpecEditor, `suggest-collar`, H0 §3.4 seam 수정 | 상수 프레임(right +X, up +Y, forward −Z); inclined·parallel-transport 유보 유지 |
| C5 `2a10c27` | timeseries 프로젝션, `hostRockDensity` optional·무기본값, 4D Restart·Loop·속도, 우측 4D results, recharts 도입 | 검증 픽스처 재생성(upstreamFingerprint 불변) |
| C6 `9f7dbaa` | 전체창 Analysis(캔버스 언마운트 + Show 3D context), KPI 타일, Planning IRR(typed), 민감도 그리드·토네이도, 공정 what-if, Schedule 탭 | IRR은 부호 변화 1회 **그리고** 괄호 안 근 존재일 때만 DEFINED; KPI 타일은 모든 탭 상단 |
| C7 `79ad128` | 데모 3개 레시피 + `scripts/bake_demos.py`, `GET /demos`, 데모 root 읽기 전용 해석 + `DEMO_READ_ONLY` 가드, File › Demos, 데모 모드(DemoPanel·Auto tour·4D loop·Clone to edit) | D1(TABULAR Longhole)에 production shaft 1개 포함; 데모는 git-ignored `data/demos/`에 배포 시 bake |
| C8 `516eeea` | 규칙 182·195·196·201 개정 + 221·222 신설, 문서, e2e(BASELINE + C&F 데모 Setup→Analysis→Export), 브라우저 수락, 최종 FULL | e2e는 C&F 데모를 임시 데이터 디렉터리에 in-process bake 후 File › Demos로 연다 |
| C9 `d35357b` | FULL 종료 수정: 레지스트리 e2e에 shaft mesh, 복사된 데모의 stat 불일치 탐지(`WORLD_PUBLICATION_STALE` 카탈로그 보고), Prettier | PR #54 첫 HEAD |

측정(이 컨테이너): bake D1 114 s · D2 85 s · D3 152 s(합 107 MB).

### 5.2 PR #54 리뷰 라운드 1 — BLOCKER B1·B2·B3 (HEAD `d35357b` 기준 리뷰)

| 커밋 | 리뷰 항목 | 내용 | 계획 대비 결정 |
|---|---|---|---|
| C10 `c84edc8` | B2 레거시 C&F 마이그레이션 | 규칙 223: `CUT_FILL_MODEL_VERSION = 2`(`stopes.json` `cutFillModelVersion` 필수, `levels.json` `productionDevelopment.modelVersion`은 C&F만 직렬화), 리더의 다섯째 read state `LEGACY`(`pre_checks`, 파생 아티팩트는 같은 스냅샷에서 "LEGACY by derivation"), typed `CUT_FILL_LEGACY_ARTIFACT`(409), `GET …/scene`이 LEVELS closure를 `reset_plan`으로 폐기 후 `migrations[]` 보고(실행 중 job → `RESET_JOB_RUNNING`, 데모는 기록 없이 typed 거부), 프런트 `SceneMigrationNotice` | 파서는 완화하지 않음. 픽스처는 `1bd68c8` worktree에서 그 코드의 라우트로 캡처한 실제 PR #53 디렉터리(`tests/fixtures/h2cf/legacy_pr53_cut_fill/`, `stat.json`으로 rule-60 stat identity 복원, 2.9 MB) |
| C11 `482d685` | B3 샤프트 선언 위치 | Setup › Access 스테이지 신설(○ Ramp only / ● Ramp + Shaft, 명시적 `scenario.shafts` 편집기, 동일 reset-plan 확인 뒤 PUT + 월드 재생성, 레이아웃 전에 결정), `ShaftSpecEditor`를 카드가 제어, Design › Shafts는 계획 + 메시만, 스테퍼 SHAFTS DONE = 계획 **그리고** 메시, `specs=[]`는 OPTIONAL 유지; e2e BASELINE 흐름에 Access 선언·Shafts 계획+메시·리셋 후 재계획 추가 | 문서(규칙 182·191, architecture, README)는 같은 파일을 공유하는 B1 문서와 함께 C12에 수록 |
| C12 `c9a5815` | B1 데모 자동 구체화 | `services/demo_materializer.py`(카탈로그가 available로 보고하지 않는 레시피만 bake, 레시피마다 index 발행, 실패 격리, 프로세스당 1회), `create_app` lifespan + `MINEGEN_DEMOS_AUTOBAKE`(기본 on; 테스트 suite·e2e·baker 앱은 off), `bake_demos.py --if-missing` + `scripts/bin/dev-setup`, `GET /demos`의 `materialization`, File › Demos "Baking…" 폴링 | 파일 배포 대신 서빙 호스트에서 in-place bake(rule 60 stat binding 불변). Docker/plain uvicorn은 startup bake에 의존 |
| C13 | §5.2 기록, README 수락 항목 7–9, 최종 FULL | — |

브라우저 수락(이 컨테이너, Playwright Chromium, 기본 설정의 라이브 uvicorn + Vite, 빈 데이터 디렉터리에 PR #53 레거시 C&F 픽스처만 복원; 스크립트 `accept_r1.py`, 페이지 오류 0):

| 케이스 | 관찰 |
|---|---|
| B1 데모 구체화 | 서버 기동 2.1 s 시점 `GET /demos` = NOT_BAKED + materialization BAKING(`demo-tabular-longhole` · WORLD, pending 2); File › Demos 메뉴에 "Baking demos… demo-tabular-longhole · LAYOUT · 2 more"; 610 s(다른 흐름과 CPU 공유) 뒤 AVAILABLE, 3개 모두 available, `index.json` bakedFromCommit `c9a5815`; Longhole 데모 열기 → SHAFTS 포함 SCHEDULE까지 DONE, 1 primary |
| B2 레거시 C&F | File › Open › `legacy-pr53-cut-fill` → 우측 열에 Migration 공지(discarded: levels.json, stopes.json, timeline.json, network.json), 스테퍼 SCENARIO·METHOD·ACCESS·LAYOUT DONE / LEVELS NEXT; 두 번째 `GET /scene` migrations=[], layoutV2·selection 유지; Levels → Generate Cut & Fill → Build network → Schedule development 모두 DONE, production SUCCESS `cutFillModelVersion` 2, 12 panels · 336 cuts |
| B3 Access 스테이지 | 새 광산 생성 후 ACCESS DONE(Ramp only)·SHAFTS OPTIONAL, primary 0; Ramp + Shaft 선택 → 편집기(Suggest collar 없음, 레벨 전) + primary 1; Apply → 확인 대화상자(월드만 있어 지울 것 없음) → 월드 재생성 → ACCESS DONE·SHAFTS WAITING; Layout → Levels → Shafts: 편집기 없음, Plan shafts 뒤에도 DONE 아님(계획만), Generate shaft mesh 뒤 DONE(1 shaft · 13 stations · 470 m, 1 barrel · 13 drives · 51 406 m³); Access 재방문 시 Suggest collar 1개, Ramp only로 바꾸면 확인 목록에 layout_v2.json … shaft_mesh.glb 8개 |

---

## 6. H2-CF — Cut & Fill 정상화

### 6.1 현 구현의 문제

1. 첫 PREP ← 최심부 레벨 중앙 크로스컷 ← 그 레벨 접근 ← 램프 전체. 램프가 바닥에 닿기 전엔 아무것도 캐지 않는다.
2. `prep_deps = {access_task} ∪ {previous_cure}`, `lift_index` 전역 → 광산 전체 단일 직렬 체인.
3. 컷이 스트라이크 전체에 걸치고 블록·패널·필러·sill 개념이 없다.
4. 블록 순서 옵션 없음.

### 6.2 교재 근거

- HRMH §3 Cut and Fill: 오버핸드 = 아래에서 위로 슬라이스, 적출 후 충전; 언더핸드 = 시멘트 충전/콘크리트 매트 아래에서 위→아래.
- HRMH, Derrick May: "backfill 광산은 이론 필요량보다 **35 % 더 많은 stoping units**" → 동시 가동 스톱 복수의 근거이지 "항상 2 패널"의 근거는 아님 → `maxConcurrentPanels`는 planning assumption.
- HRMH, Fred Nabb: 벽암이 광석보다 훨씬 견고하면 top-down, 반대면 bottom-up → 블록 순서는 옵션.
- HRMH, Thibodeau(1999): 임시 sill pillar, center-out, 패널 스트라이크 길이 상한.
- SME Fig. 10.16 오버핸드 C&F: 비시멘트 암석 충전이 기본, **시멘트 충전이 스톱 바닥(sill mat)**; Fig. 10.17 언더핸드: 시멘트 충전 아래 "Level in Production"; Table 10.3.

### 6.3 모델 — 두 축, 유효 조합만

```text
stopingDirection : OVERHAND | UNDERHAND                (스톱 블록 안의 슬라이스 방향)
blockOrder       : SHALLOW_TO_DEEP | DEEP_TO_SHALLOW   (블록 착수 순서)
```

| 조합 | 처리 | 이유 |
|---|---|---|
| OVERHAND + DEEP_TO_SHALLOW | 구현. 현행 의미 + 패널 동시성 | 하부 블록이 먼저 충전되므로 sill mat 불필요 |
| OVERHAND + SHALLOW_TO_DEEP | **구현, 기본값.** 최심부가 아닌 각 블록의 최하단 리프트 충전 = `cemented = true`, `sillMatCureDays` 적용 | 하부 블록의 마지막 리프트가 상부 블록 충전재를 천반으로 두고 채굴되므로 **cemented sill mat 없이는 성립하지 않는다** |
| UNDERHAND + SHALLOW_TO_DEEP | typed `UNSUPPORTED_STOPING_DIRECTION` | 매 컷 cemented fill + 양생 선행 + footwall attack ramp — 별도 phase |
| UNDERHAND + DEEP_TO_SHALLOW | typed `UNSUPPORTED_STOPING_DIRECTION` | 실무 관행으로 열거하지 않음 |

rule 78/192 방식: 스키마는 두 축으로 열어 두고, 구현은 OVERHAND만, 나머지는 silent fallback 없이 typed 거부. "top-down/bottom-up" 어휘는 코드·UI에서 쓰지 않는다(언더핸드와 혼동).

**구조**: 레벨 구간 × 스트라이크 패널 = 스톱 블록. 블록 안은 리프트 × 컷.

- `panelLengthM`(기본 60): 구간 스트라이크를 등분(`n = ceil(span/target)`, rule 194). 컷은 패널 안에서 `cutLengthM` 등분.
- `ribPillarWidthM`(기본 0): 패널 사이 rib pillar. > 0이면 R&P PILLAR와 같은 retained-material 엔티티(기하 + `tonnesEquivalent`, 스케줄 없음). 0이면 패널은 스케줄 단위.
- `maxConcurrentPanels`(기본 2): 동시 생산 패널 상한. **자원 솔버가 아니라 명시적 선행관계** — 패널 k+N의 첫 PREP ← 패널 k의 마지막 CURE. 착수 순서 결정론적: 블록 가용 순 → 패널 center-out. rule 82 유지.
- `sillMatCureDays`(기본 28): cemented 충전의 양생. 비시멘트 충전의 CURE는 기존 값.
- 전부 `CutFillParameters`의 registry canonical default(rule 194), UI 카드에 노출. "planning default, never engineering truth" 표기.

**블록 가용 조건**: 하부 레벨 LEVEL_ACCESS + 드리프트 + 해당 패널의 중앙 크로스컷 완료. 리프트별 접근 기하(attack ramp)는 비범위.

**컷 체인**: PREP → STOPING → MUCKING → BACKFILL → CURE. 패널 안에서 직전 컷 CURE 뒤 다음 컷, 리프트 안 스네이크 유지. SHALLOW_TO_DEEP에서 하부 블록의 최상단 리프트 PREP ← 바로 위 블록 sill mat CURE (명시적 의존, 보통 이미 만족).

### 6.4 산출 변경

`CutFillPayload`: `blockId`, `panelId`, `cemented` 플래그(backfill), `pillars[]`(선택), `sequencing {stopingDirection, blockOrder, maxConcurrentPanels, panelLengthM, ribPillarWidthM, sillMatCureDays}`. `timeline.json`은 `targetKind = CUT` 그대로, 의존 구조만 변경. `integrity.py` 확장(패널별 체인, cemented ↔ 블록 최하단 리프트 일치).

### 6.5 테스트·픽스처

- 임의 day에 ACTIVE 패널 수 ≤ `maxConcurrentPanels`; SHALLOW_TO_DEEP에서 첫 생산일 < 램프 완료일; 최심부 제외 모든 블록 첫 컷 `cemented = true`; DEEP_TO_SHALLOW + `maxConcurrentPanels = 1` + `panelLengthM ≥ span`이 기존 C&F 픽스처의 의존 구조를 재현.
- C&F 픽스처는 **의도적으로** 재생성하고 비교 문서를 남긴다. 롱홀 baseline byte-identical(BLOCKING).

### 6.6 MineExchange 1.3.1 (additive patch)

- 1.4(패널/필러 엔티티)는 유예. 단 1.3 exporter가 `methodParameters`의 새 필드를 **조용히 빠뜨리는 상태는 금지** → `semantics/mining_method.json`의 C&F 파라미터 DTO만 additive 확장, `production/cut_fill.json`에 `blockId/panelId/cemented` 추가. 번들 버전 `1.3.1`. Longhole·R&P 번들 byte-identical(기존 게이트).
- AnyLogic `production_units.csv`: rib pillar는 PILLAR 행(`retained`) 재사용, backfill 행에 `cemented` 컬럼 추가.

---

## 7. H2-SH — Shaft

### 7.1 Shaft mesh (렌더 전용)

- 새 artifact `derived/shaft_mesh.{json,glb}`, registry에서 `shafts.json` 하류(fingerprint = scenario + shafts). shafts 재생성 → shaft_mesh 삭제; shaft_mesh 재생성은 아무것도 지우지 않음. **development_mesh에 넣지 않는다**(넣으면 shaft 재생성이 levels 사이클을 건드림).
- 축: 원형 단면(spec `diameter`)을 수직선 따라 sweep. 수직축은 프레임이 상수(고정 수평 basis `right = +X, forward = +Y`) — rule 26의 parallel-transport 유보는 **경사 샤프트**에만 남긴다(rule 182 문구 개정: "vertical-only mesh 구현, inclined 유보").
- station access: `shafts.json`이 선언한 직선 드라이브를 기존 gravity-aligned sweep(`build_ring_chain/…`, rule 166 머시너리)으로. 단면은 shafts.json 선언값(없으면 현재 drive 생성 시 쓰는 프로필 — 구현 때 확인하고 선언 필드로 올린다).
- QA: 축은 CAP–CAP 닫힌 솔리드(collar 캡·sump 캡), station access는 OPEN(축 쪽)–OPEN(레벨 노드 쪽) manifold-with-boundary(rule 166 분리 QA 그대로). 부울·교차 CSG 없음.
- 4D reveal: 같은 ring-interval 메타데이터 발행, 매핑은 `geometryRef` 소유 artifact(shafts.json) → piece id `SHAFT:<shaftId>:<segment>` / `SHAFT_STATION_ACCESS:<shaftId>:<levelId>`; 매핑 실패는 중심선 렌더 유지(rule 173 fail-closed).
- 프런트 `ShaftLayer`: mesh가 있으면 mesh, 없으면 현 `<line>`. Walkthrough 비포함(rule 187 composition 불변).

### 7.2 Shaft UX

- Shafts 단계 편집기: role, diameter, collarStandoff, maximumStationAccessLength, capabilities, (선택) collar 좌표. "Suggest collar"는 planner의 기본 규칙(rule 182) 재사용 — 프런트는 기하를 만들지 않는다.
- station별 typed 실패와 한계값 표시(`ShaftFailureCode`, `shafts/planner.py:698-756`).
- 기본값(200 m 등)은 바꾸지 않는다. 저장 시나리오 + 골든으로 실패 센서스를 **기록만** 하고(`python -m minegen.regression shaft-census`), 조정은 수락 후.
- `specs=[]` 기본은 유지(샤프트는 명시적 선택).

---

## 8. H3 — 4D·Analysis

### 8.1 timeseries 프로젝션 (백엔드)

`GET …/analysis/timeseries?bucketDays=` — rule 197 방식(바운드 스냅샷, 저장 없음, READ_SNAPSHOT_CHANGED). 버킷별 + cumulative 컬럼:

- 개발 연장(m, edge type별), 개발 굴착 체적(m³) — 톤은 `scenario.geology.hostRockDensity`(optional, **기본값 없음**, rule 37)가 있을 때만; 없으면 `developmentTonnes = null` + `NOT_CONFIGURED`.
- 생산 톤(t), 뒤채움(m³, cemented 분리), retained pillar는 별도.
- economics 설정 시 cost/revenue/net/cumulative(rule 202 버킷 그대로).
- 어휘: "excavated development rock", waste/reserve 금지(rule 198).

### 8.2 4D 뷰

- `timelineStore`에 `loop`; `[◀][▶][↻] 1× 5× 20× ☑ LOOP`.
- 우측 RESULTS 패널: Current day · Development/Production/Backfill 상태 · 누적 곡선(Development excavation, Production tonnes, Cost, Revenue, Net, Cumulative). 데이터는 전부 백엔드 버킷, 프런트는 누적합도 하지 않는다.
- 차트 라이브러리 **`recharts` 도입**(rule 15: 처음 쓰는 커밋에서 사유 — 차트 10종 이상, 손 SVG 유지비).

### 8.3 Analysis 전체창

- ANALYSIS 모드에서 `MineCanvas` 언마운트(`App.tsx:32` 조건부), "Show 3D context"로 split view.
- 레이아웃: KPI 타일(NPV · IRR · Mine life · First production) → 탭(Overview · Economics · Sensitivity · Schedule · Rules · Layouts · Simulation Results) → 큰 차트 2개 → 표. 어휘는 rule 198–201(면책문 유지).
- **Planning IRR**: 버킷 순현금흐름, rule 202의 mid-bucket 할인과 같은 시점 규약, 이분법. 순현금흐름 부호 변화가 정확히 1회(음→양)일 때만 정의; 아니면 `irr = null, irrStatus = NOT_DEFINED, reason = NO_SIGN_CHANGE | MULTIPLE_SIGN_CHANGES`(rule 34: NaN 금지). rule 201 "No IRR" 문구 개정.
- **민감도(토네이도)**: 입력 = gross revenue/t, development cost, mining cost, processing cost, backfill cost, initial capital, discount rate(경제 — cashflow만 재실행), development rate, mining rate(공정 — `MineTimelineBuilder` 메모리 재실행). ±10/20/30 %. 출력 = Planning NPV, Planning IRR, mine duration, first production day. 저장 없음, 결과에 "what-if override, not the scenario value" 명시. 이름은 정확히 **Gross revenue per mined tonne**; 금속가격·품위·회수율 모델은 비범위(rule 199 불변).
- Layout 비교는 "Option n" 라벨(PR-1)과 rule 204–206 그대로.

---

## 9. H4 — 데모

- 사전 생성 시나리오 3개: TABULAR Longhole, TABULAR Cut & Fill(새 시퀀스), WARPED_VEIN(world + layout-v2 + levels). `scripts/bake_demos.py`가 `data/demos/<id>/`에 끝까지 생성(경제 가정 포함, DEMO/SYNTHETIC 표기). `GET /demos`는 `data/demos/index.json`을 읽는다.
- File › Demos: **Open demo** = 데모 시나리오를 읽기 전용으로 연다(derived 복사 없음 — artifact 바인딩을 건드리지 않기 위해). "Clone to edit"는 scenario 문서를 새 id로 PUT(world는 같은 seed로 재생성, rule 119).
- 데모 모드: 생성 버튼 숨김(viewer-only), **Auto tour**(카메라 프리셋 순환), **4D loop** 켬.
- HF Space(D0: 단일 오리진 Dockerfile, 생성 API 차단 빌드)는 최종 수락 뒤 별도.

---

## 10. 확정한 기본값·결정 (수락 후 바꿀 수 있음)

| # | 항목 | 결정 |
|---|---|---|
| 1 | C&F `stopingDirection` / `blockOrder` 기본 | OVERHAND / SHALLOW_TO_DEEP (+ cemented sill mat) |
| 2 | `maxConcurrentPanels` / `panelLengthM` / `sillMatCureDays` / `ribPillarWidthM` | 2 / 60 / 28 / 0 |
| 3 | 금속가격 수익 모델 | 넣지 않음. 민감도는 gross revenue/t까지 |
| 4 | 차트 라이브러리 | `recharts` |
| 5 | `hostRockDensity` | `scenario.geology.hostRockDensity` optional, 기본값 없음 |
| 6 | 데모 | 3개(§9) |
| 7 | UI 언어 | 영문 유지 |
| 8 | MineExchange | 1.3.1 additive; 1.4는 수락 후 |
| 9 | Shaft 기본값 조정 | 센서스 기록만, 조정은 수락 후 |
| 10 | `topMarginReference` 옵션 | 수락 후 별도 |
| 11 | Walkthrough branch teleport / 데모 배포(D0) | 수락 후 |

---

## 11. 최종 수동 수락 체크리스트 (두 PR 머지 후 한 번)

| # | 지적 | 확인 방법 |
|---|---|---|
| 1 | UI 이해 | 힌트 없이 Setup→Export 한 번에. 주 버튼 항상 하나 |
| 2 | 초기화 | Levels에서 Reset from here → 확인창에 Network·Production·Timeline… 나열 → 재생성 |
| 3 | Scenario→World 순서 | Create mine 한 번으로 world까지 |
| 4 | Export 위치 | File 메뉴 + 7단계 |
| 5 | ⓘ | 좌측 어느 카드에서도 전부 보임 |
| 6 | 데모 | File › Demos › Open → auto tour + 4D loop |
| 7 | 좌 컨트롤/우 진행 | 우측 STATUS & RESULTS에 상태·지표·실패 사유 |
| 8 | TABULAR Level Dev | seed 42 → SUCCESS, "L01 excluded, min topMiningMargin 11.87 m" 표시 |
| 9 | 4D 반복 | LOOP 체크 |
| 10 | View 패널 | 우하단 Visibility 트리 |
| 11 | Go To | levels 실패 시나리오에서도 Portal + turnout 목록·이동, 분기점 가시 |
| 12 | 4D 그래프 | 우측 누적 곡선 + day 커서 |
| 13 | Analysis 전체창 | 캔버스 사라지고 큰 차트 |
| 14 | Option n | Layout 단계·Layouts 탭 |
| 15 | 민감도·IRR·기간 | Sensitivity 탭 토네이도, KPI IRR(미정의면 사유) |
| 16 | Method 위치 | Setup 2번째, 나중 변경 시 확인창 |
| 17 | Shaft | 편집기에서 spec 추가 → Plan → 3D mesh(축·station·access) |
| 18 | C&F 시퀀스 | C&F 데모 4D: 상부 블록부터, 패널 2개 동시 ACTIVE, 첫 컷 cemented, 첫 생산 < 램프 완료 |

---

## 12. 규칙 개정 목록

| 규칙 | PR | 변경 |
|---|---|---|
| 141 | 1 | 서비스 가능 = 단면 존재 ∧ footwall 접촉 존재; `excludedLevels/unservedIntervals` 보고 |
| 191 | 1 | 좌측 패널 구조 조항 → 신규 셸 규칙(리본·스테퍼·3분할·뷰 모드 분리)으로 대체, 원칙 승계 |
| 신규 | 1 | Reset = 레지스트리 클로저 삭제, preview/실행 동일 함수, 프런트 의존 그래프 없음 |
| 신규 | 1 | Walkthrough Go To authority = `RAMP_JUNCTION.chainage`, network 부재 시 폴백 순서 |
| 182 | 2 | 수직 shaft mesh 구현(상수 프레임), inclined·parallel-transport 유보 유지, `shaft_mesh` artifact 라이프사이클 |
| 195 | 2 | 패널·rib pillar·cemented sill mat 기하 |
| 196 | 2 | 두 축, 유효 조합 표, 패널 체인 + 동시성 선행관계, UNDERHAND typed 거부 |
| 201 | 2 | Planning IRR(typed 비존재)·민감도·공정 what-if 허용, 금속가격 모델 여전히 없음 |
| 신규 | 2 | timeseries 프로젝션(rule 197 계열), `hostRockDensity` optional·무기본값 |
| 신규 | 2 | 데모 = 읽기 전용 baked 시나리오, 생성 API 비노출 |

---

## 13. Claude Code 지시문 (복사용)

### PR-1

```text
docs/hardening-plan.md를 읽어라. §2 헤더대로 브랜치 hardening-1-shell을 main에서 만들고
§3(H0)과 §4(H1)를 §2의 커밋 순서대로 구현하라. 커밋마다 scripts/verify.py fast,
PR 종료 전 full + frontend 4종 + §4.5 e2e. 골든·parity 불변 조건은 §2 그대로.
규칙 개정은 §12의 PR-1 행만. 끝나면 rule 126 보고 형식으로 push 승인을 요청하라.
```

### PR-2 (PR-1 머지 후)

```text
docs/hardening-plan.md를 읽어라. §5 헤더대로 브랜치 hardening-2-engine-analysis를 main에서 만들고
§6(H2-CF), §7(H2-SH), §8(H3), §9(H4)를 §5의 커밋 순서대로 구현하라. 기본값은 §10을 그대로 쓴다.
롱홀 baseline은 BLOCKING, C&F 픽스처는 의도적 재생성 + 비교 문서. §5의 폴백 분할점은
full 종료가 막힐 때만 쓴다. 규칙 개정은 §12의 PR-2 행만. 끝나면 rule 126 보고 형식으로 push 승인을 요청하라.
```
