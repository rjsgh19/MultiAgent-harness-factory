# @generated
"""LLM 파서 — PRD 전체를 LLM으로 읽어 구조화된 JSON으로 추출.

정적 파싱 없이 100% LLM에 의존하여 마크다운을 분석한다.
"""
# BEGIN GENERATED
from __future__ import annotations

import json
from typing import Any, Callable

LLM_PARSER_SYSTEM = """\
당신은 최고의 소프트웨어 아키텍트다.
사용자의 PRD 마크다운 전체를 읽고, 아래 JSON 스키마에 맞춰 완벽하게 구조화된 데이터를 추출하라.
테이블 형태가 아니어도, 개요나 줄글에 있는 의도를 파악하여 채워넣는다.
출력은 반드시 순수한 JSON만 반환한다. 마크다운 코드블록(```json)이나 다른 설명은 절대 추가하지 마라.

[JSON 출력 스키마]
{
  "project_name": "프로젝트명",
  "domain": "도메인 식별자 (예: my_domain)",
  "overview": "전체 설명 요약",
  "functions": [
    {
      "name": "함수명",
      "parameters": [{"name": "param1", "type": "dict"}],
      "returns": "dict",
      "docstring_required": true
    }
  ],
  "forbidden_imports": ["패키지명1", "패키지명2"],
  "invariants": [
    {
      "id": "INV-001",
      "description": "설명",
      "required_keys": ["key1"],
      "pattern": "regex"
    }
  ],
  "stages": [
    {
      "id": "단계id",
      "nodes": ["노드1", "노드2"],
      "on_fail": "실패시라우팅노드 (옵션)"
    }
  ],
  "routing_rules": [
    {
      "when": "조건",
      "then": "다음노드",
      "payload": "페이로드 (옵션)"
    }
  ],
  "agents": [
    {
      "name": "에이전트명",
      "role_summary": "역할",
      "forbidden": "금지사항",
      "output_keys": ["key1", "key2"]
    }
  ],
  "extra_constraints": ["제약1", "제약2"],
  "tests": [
    {
      "type": "unit",
      "filename": "test_name.py",
      "description": "검증 내용"
    }
  ]
}
"""


def parse_prd_with_llm(
    raw_markdown: str,
    llm_complete: Callable[[str, str], str],
) -> dict[str, Any]:
    """LLM을 사용해 PRD 마크다운 전체를 파싱한다."""
    user_prompt = f"다음 PRD를 읽고 구조화된 JSON으로 추출하라:\n\n{raw_markdown}"
    
    try:
        raw_output = llm_complete(LLM_PARSER_SYSTEM, user_prompt)
        
        # ```json 마크다운 등이 섞여 있을 경우를 대비한 클렌징
        if "```json" in raw_output:
            raw_output = raw_output.split("```json")[1].split("```")[0]
        elif "```" in raw_output:
            raw_output = raw_output.split("```")[1].split("```")[0]
            
        parsed = json.loads(raw_output.strip())
        if not isinstance(parsed, dict):
            raise ValueError("LLM 반환값이 JSON dict가 아님")
            
        # 필수 키 보장
        for key in ["functions", "agents", "tests", "stages", "routing_rules", "invariants", "extra_constraints", "forbidden_imports"]:
            if key not in parsed:
                parsed[key] = []
                
        return parsed
    except Exception as e:
        raise ValueError(f"LLM 파싱 실패: {e}")


LLM_VALIDATOR_SYSTEM = """\
당신은 엄격한 QA 엔지니어다.
사용자가 제공한 원본 PRD 마크다운과, 이를 파싱해 추출한 JSON 데이터를 비교하라.
추출된 JSON 안에 원본 PRD 마크다운에 언급되지 않은 내용(없는 함수, 없는 에이전트, 지어낸 제약조건 등)이 '지어내어(Hallucinate)' 들어갔는지 검사하라.
만약 원본을 벗어난 내용이 발견된다면, 그 문제점들을 구체적인 문자열 배열로 반환하라.
완벽하게 일치하고 지어낸 내용이 없다면 빈 배열 []을 반환하라.
출력은 반드시 JSON 배열(List of strings)로만 응답하라. 다른 말은 추가하지 마라.
"""

def validate_parsed_prd_with_llm(
    raw_markdown: str,
    parsed_dict: dict[str, Any],
    llm_complete: Callable[[str, str], str],
) -> list[str]:
    """파싱된 JSON이 원본 PRD 내용을 벗어나지 않았는지 LLM으로 교차 검증한다."""
    user_prompt = f"[원본 PRD]\n{raw_markdown}\n\n[추출된 JSON]\n{json.dumps(parsed_dict, ensure_ascii=False, indent=2)}\n\n위 JSON에 원본에 없는 내용이 있는지 검사하라."
    
    try:
        raw_output = llm_complete(LLM_VALIDATOR_SYSTEM, user_prompt)
        
        if "```json" in raw_output:
            raw_output = raw_output.split("```json")[1].split("```")[0]
        elif "```" in raw_output:
            raw_output = raw_output.split("```")[1].split("```")[0]
            
        errors = json.loads(raw_output.strip())
        if not isinstance(errors, list):
            return ["검증 LLM의 출력이 배열 형태가 아닙니다."]
        return errors
    except Exception as e:
        return [f"LLM 검증 과정 중 오류 발생: {e}"]
# END GENERATED
