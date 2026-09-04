# 문서 버전과 사이트 배포

이 저장소는 규정 문서의 버전과 운영 사이트 배포 이력을 별도로 관리한다. `main`에 머지하는 것만으로는 GitHub Pages가 바뀌지 않는다.

## 식별자

- `edition`은 공식 규정의 연도다. 예: `2026`.
- `revision`은 같은 연도 내에서 각 문서가 따로 가지는 1부터 시작하는 일련번호다.
- 문서 버전은 `<edition>-v<revision>`, 문서 태그는 `<document>-<edition>-v<revision>`이다. 예: `formula-technical-2026-v2`.
- 사이트 태그는 `site-YYYYMMDD-vN`이다. `N`은 KST 기준 같은 날짜에 1부터 연속적으로 올린다. 예: `site-20260903-v1`.

`formula-technical`과 `formula-competition`의 revision은 서로 독립적이다. 한 문서만 바뀌면 그 문서의 revision만 증가한다.

## 문서 revision 규칙

`scripts/release_contract.py` 가 이전 문서 Release manifest의 `document_digest`와 현재 입력을 비교한다. 최초 Release는 반드시 v1이며, digest가 바뀌면 revision을 정확히 하나 올려야 하고 바뀌지 않았다면 올릴 수 없다. revision을 건너뛰거나 이전 태그·Release manifest가 빠진 상태도 CI가 거부한다.

Digest는 다음 문서 산출물 입력을 포함한다.

- revision과 임시 PDF/AUX 경로를 제외한 catalog 문서 메타데이터
- 해당 `rules.tex`, LaTeX entrypoint, 문서 이미지
- LaTeX 템플릿, HTML 변환·빌드·릴리스 코드
- Python 요구사항과 SHA-256으로 고정된 폰트 입력

`style.css`, `viewer.js`, `home.js`, GitHub Actions, 설명 문서만 바뀌는 경우 문서 revision은 올리지 않고 새 site 태그로만 배포한다. 이 경계는 공유 사이트 표현을 바꾸는 일과 규정 판본을 바꾸는 일을 분리한다.

## 영구 규정 키 연속성

소비자는 `rules-index.json`의 `rule_key`를 저장하므로, revision이 올라가는 PR에서 `check-catalog`는 이전 문서 Release의 `rules-index.json`과 현재 빌드를 비교한다. 이전 Release에 있던 키가 사라지면 catalog 문서 항목의 `retired_rule_keys`에 선언된 경우에만 통과하고, 선언된 키가 아직 인덱스에 남아 있으면 실패한다. 새 키 추가는 자유롭다. 키 작성 규칙은 [연동 가이드](rule-refs.md)에 있다.

## 문서 Release

1. 변경 PR의 CI가 현재 digest와 `revision`의 일치를 검증한다.
2. PR을 `main`에 머지한다.
3. 변경된 문서만 현재 commit에 문서 태그를 만들고 push한다.
4. `Release document` 워크플로가 태그가 `main` 이력인지, revision이 연속적인지, 이전 digest와 실제로 다른지를 확인한다.
5. 프로비넌스 attestation과 함께 PDF, 웹 ZIP, `rules-index.json`, Release manifest, `SHA256SUMS`를 GitHub Release에 보존한다.

Release 산출물은 태그 이름으로 namespace되며 Release manifest는 `schemas/document-release.schema.json`을 따른다.

## 사이트 승격

1. catalog에 적힌 모든 문서 버전의 GitHub Release가 성공했는지 확인한다.
2. `main`의 승격할 commit에 현재 KST 날짜의 다음 `site-YYYYMMDD-vN` 태그를 만들고 push한다.
3. `Release and deploy site` 워크플로가 태그 순서, 문서 Release digest, 아카이브 체크섬과 attestation을 검증한다.
4. `github-pages` Environment의 required reviewer가 승인하면 사이트 Release를 생성하고 Pages에 배포한다.

Pages는 항상 가장 최근에 승인된 본만 제공한다. 역사적 PDF·HTML·인덱스·manifest·체크섬은 GitHub Releases에서 조회한다. 사이트 Release manifest는 `schemas/site-release.schema.json`, 운영 진입점은 v2 `schemas/rules-manifest.schema.json`을 따른다.

## 롤백

`Release and deploy site` workflow를 수동 실행하고 기존 `site-*-v*` 태그를 `rollback_tag`으로 입력한다. 워크플로는 GitHub Release에서 아카이브를 받아 `SHA256SUMS`와 GitHub attestation을 다시 검증하고, 동일한 Environment 승인을 거쳐 재배포한다. 롤백은 기존 Release를 변경하거나 새 문서/site 버전을 만들지 않는다.

## 저장소 보호 조건

이 계약은 다음 GitHub 설정과 함께 운영한다.

- `main`: pull request와 `Build PDF/HTML` 필수, force push·삭제 금지, 승인 인원 0명
- `github-pages`: 배포 branch/tag 제한과 required reviewer
- 문서/site Release: `vN` 형식의 고유 태그 사용

초기 배포는 두 문서의 `v1` Release와 첫 site Release부터 시작한다.
