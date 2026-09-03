# `sheet_template.rule_refs` 연동 계약

소비 서비스는 별도 검색 매핑 테이블 대신 `sheet_template`에 `rule_refs` JSON 컬럼 하나를 둘 수 있습니다. 이 저장소는 소비자 데이터베이스를 수정하지 않으며, 검증용 [JSON Schema](../schemas/rule-refs.schema.json)를 제공합니다.

```json
{
  "status": "verified",
  "references": [
    {
      "edition": 2026,
      "document": "formula-technical",
      "clause_id": "formula-technical-10-9",
      "citation": "제10조 9항",
      "source_hash": "sha256:..."
    }
  ]
}
```

`source_hash`는 해당 `rules-index.json` 엔트리의 `content_hash`입니다. 공식 PDF 전체의 `pdf_hash`와는 목적이 다릅니다. 참조 배열은 한 문항이 여러 조항을 가리킬 수 있게 하며, 직접 대응 규정이 없는 운영 문항은 아래처럼 명시합니다.

`content_hash`는 조항의 표시 텍스트를 Unicode NFC로 정규화하고 연속 공백을 하나로 만든 값에, 조항에 포함된 이미지의 SHA-256을 더해 계산합니다. 내부 참조의 표시 문구는 대상 앵커 ID로 정규화합니다. `edition`, 현재 조항 ID, 인용 표기는 해시 입력에서 제외하므로 다음 연도에 내용이 그대로인지를 비교할 수 있습니다. 상위 항과 조 단위 해시는 그 아래 하위 조항 전체를 포함합니다.

```json
{ "status": "no_direct_rule", "references": [] }
```

## 다음 연도 템플릿 복사

기본 동작은 참조를 그대로 복사하지 않고 `{ "status": "needs_review", "references": [] }`로 초기화하는 것입니다. 단, 다음 조건을 모두 만족하면 자동 승계할 수 있습니다.

1. 원본과 대상 문항의 `field_key`가 같다.
2. 다음 연도 `rules-index.json`에 같은 `clause_id`가 있다.
3. 이전 참조의 `source_hash`와 다음 연도 엔트리의 `content_hash`가 같다.

자동 승계 시 `edition`, `citation`, `source_hash`는 다음 연도 엔트리의 값으로 다시 기록하고 상태를 `verified`로 둡니다. 하나라도 실패하면 `needs_review`를 유지합니다. 이전 연도의 문항은 현재 규정으로 강제 이동하지 않고 당시 `edition`의 문서와 연결합니다.

## URL 조립

1. `/rules-manifest.json`에서 `(edition, document)`가 일치하는 항목을 찾습니다.
2. 그 항목의 `web_path`에 `#<clause_id>`를 붙입니다.
3. `document`와 `clause_id`가 스키마를 통과하고, 매니페스트가 이 사이트에서 내려온 경우에만 링크로 노출합니다.

이 방식은 데이터에 임의의 외부 URL이 들어오는 것을 막고 사이트 경로 변경도 매니페스트 한 곳에서 처리합니다.
