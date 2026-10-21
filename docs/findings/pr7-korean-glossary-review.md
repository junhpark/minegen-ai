# Hardening PR-7 — Korean glossary review round (Park, 2026-10-21)

Park reviewed the Korean–English UI glossary generated from the PR-6 head
(`e80c7eb`: `frontend/src/i18n/ko.ts`, 897 UI strings; `docs/i18n/terminology.json`,
121 terms) in two passes (v2 review + v3 additions: the "공칭" replacement and the
English co-naming rule) and returned the workbook with the corrections in the edit
columns. This PR applies that review verbatim; nothing was retranslated on the
machine side.

## What changed

| Set | Count | Notes |
| --- | --- | --- |
| UI string values (`ko.ts`) | 132 of 897 | priorities as marked by Park: [필수] mistranslations, [권장] standard-term alignment, [선택] literature spelling; keys, order and placeholders unchanged |
| Terminology adopted terms | 20 | e.g. Drift → 하반갱도, Stope → 채굴장(스토프), Capability → 용도, Feasible / Infeasible → 실현 가능 / 실현 불가, Raise → 승갱도(레이즈), Warped vein → 굴곡 맥상 광체, Coverage → 커버리지, Longitudinal → 주향 평행형 |
| Terminology reasoning edits | 13 | Level's "갱도 중단(中段)" corrected to 편(片)·작업 레벨 (중단 = sublevel); Dip 우수법칙 → 오른손 법칙; Crosscut, Level entry, Shaft station, Sublevel interval; empty 근거 cells filled (Planning IRR, Minimap, Generate / Regenerate); [유지] opinions appended as 검토(2026-10) |
| New terms | 12 | Drift (general lateral heading) 수평갱도 · Ore drive / vein drift 연맥갱도(금속광) / 연층갱도(석탄) (reference only, literature unconfirmed) · Haulageway 운반갱도 · Sublevel 중단(서브레벨) · Orebody exclusion buffer 광체 배제 거리 · Access screen 선별 · Expanded states 확장 상태 · Authority (assessment) 판정 유형 · Nominal size / thickness 기준 크기 / 기준 두께 · Nominal volume 이론 체적 · Layout family 배치 유형 · Watertight (mesh) watertight |

`docs/i18n/glossary-ko-en.xlsx` is regenerated from the two files by
`scripts/i18n_glossary.py` (897 strings, 133 terms).

## Decisions recorded by the reviewer

| English | before | after | reason (Park) |
| --- | --- | --- | --- |
| Drift (footwall drive) | 드리프트(하반 주향 갱도) | 하반갱도 | the level backbone follows the footwall outside the ore (curved for WARPED); HRM "footwall drift", 상동광산 "하반갱도"; "연층갱도" connotes a drive inside a seam |
| Stope | 스토프(채광장) | 채굴장(스토프) | SNU OCW; 광산안전기술기준 §44 (the mined-out void is 채굴적) |
| Development | 개발 갱도(굴진) | 굴진(갱도) | quantities, costs and tasks are 굴진; the object is 갱도 (레벨 갱도, 생산 갱도); "광산 개발 흐름 / 일정" (the whole mine) keeps 개발 |
| Warped vein | 습곡 맥상 광체 | 굴곡 맥상 광체 | warp ≠ fold (습곡) |
| Feasible / Infeasible | 타당 / 부적합 | 실현 가능 / 실현 불가 | avoids "타당성 조사" (feasibility study); hard-constraint pass / fail |
| Capability | 기능 | 용도 | the definition is "what an edge permits" — not a function; English co-named only in ⓘ sentences |
| Raise | 레이즈(승갱) | 승갱도(레이즈) | 광산안전기술기준 §51 |
| Shaft collar | 수갱 갱구(콜라) | 수갱 갱구(칼라) | loanword spelling; "수갱 갱구" everywhere a shaft collar could be confused with the ramp portal |
| Level (reasoning only) | 갱도 중단(中段) | 편(片)·작업 레벨 | 중단 is sublevel; the regulation says 편 |
| Nominal size / thickness / volume | 공칭 … | 기준 크기 / 기준 두께 / 이론 체적 | "공칭" is a KS pipe / thread dimension word; the vein morphology varies the local size around these reference values; the volume is area × 3-D centerline length |
| Coverage (communication) | 통달 범위 | 커버리지 | "통달" is radio jargon; aligns with "레벨 커버리지"; the sensor "감시 범위" stays |
| Layout v2, Hybrid-A*, LHOS, Cut & Fill, Room & Pillar, SLC, watertight | translated / transliterated | English kept or co-named | proper names and engine / method names that the literature and external tools use in English |

English co-naming rule (Park): proper names, engines, algorithms, file formats and
international abbreviations stay English; a Korean name whose English form is the
more common one is co-named once in the ⓘ explanation sentence
(충전 채광법(Cut & Fill), 하반갱도(footwall drift), 용도 그래프(capability graph));
buttons, stage chips, short labels and templates are never co-named; established
loanwords (램프, 크로스컷, 스테이션, 섬프, 헤딩, 벤치, 커버리지) stay.

Sources Park cited: 서울대 OCW 「광산개발 관련 주요 용어」; 광산안전기술기준
(광산안전법 제7조의2); SME Mining Reference Handbook (2020) ch. 10; Hard Rock
Miner's Handbook ch. 3 / 11; Penn State MNG 230; 상동광산 연혁; 한국터널지하공간학회
(주방식·암주); 경상국립대 단층 손상대 연구.

Open items Park listed for a later check: the literature source of "연맥갱도"
(kept as a reference row only), a domestic "횡갱" usage for crosscut, the standard
Korean names of Longhole Open Stoping and Shrinkage Stoping, and whether the site
says 섬프 or 집수정 and 칼라 for collar.

## How it was applied and checked

- The edit columns of the returned workbook were applied by key: 132 UI rows with a
  "한국어 (수정)" value (no direct edits of the "현재" column), each checked to carry
  exactly the placeholders of its English key; `ko.ts` was regenerated with its header
  and entry order unchanged and formatted by prettier — the diff is 132 value lines
  per side and nothing else.
- A leftover scan of the new dictionary for the retired words (드리프트 · 스토프 ·
  채광장 · 기능 그래프 · 타당 (excluding 타당성) · 부적합 · 통달 · 패밀리 · 배치 v2 ·
  컷앤필 · 공칭 · 개발 갱도 · 레벨 개발 · 레이즈 · 콜라 · 습곡 · 왜곡 · 권위 ·
  서브레벨 · 펼침 · 유닛) finds one hit, "사갱 종단면" for `Decline profile`, which is
  the vertical-profile sense the reviewer kept on purpose.
- The dictionary invariants test (`frontend/src/i18n/i18n.test.tsx`: no empty entry,
  every placeholder survives, no Korean key) and the browser e2e's Korean switch
  assertion ("설정") are unaffected; no test string among the changed values.
