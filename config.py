# -*- coding: utf-8 -*-
"""빈틈노트 설정. 숫자와 이름은 여기 한 곳에서만 바꾼다."""

LLM_MODEL = "claude-sonnet-5-5"   # 이 한 줄만 바꾸면 언어 모델 교체 (예: "claude-haiku-5-5")
STT_MODEL = "whisper-1"           # None이면 음성 인식 끄기(대본 붙여넣기만 사용)
DIAG_MIN_PCT = 20                 # 출제 가능성이 이 값(%) 이상인 개념은 전부 진단. 미만은 결과와 상관없이 "복습만"
ESSAY_MIN_PCT = 50                # "섞어서" 모드: 출제 가능성이 이 값 이상이면 서술형, 미만이면 객관식
MAX_PAGES = 120                   # 분석할 최대 쪽수
MAX_EVIDENCE_PAGES = 8            # 진단·설명 호출에 넣는 근거 쪽 상한
MAX_MATERIAL_MB = 30              # 강의자료 파일 크기 상한
MAX_AUDIO_MB = 25                 # 녹음 파일 크기 상한 (음성 인식 API 제한)
AUTO_EXPLAIN_TOP = 3              # S04에서 자동으로 설명을 만드는 상위 개수 ('지금 당장'은 개수와 상관없이 전부)
AI_MAX_TOKENS = 4000              # 문제 만들기·채점·보완 설명(호출 3-A/3-B/3-C/4)의 답 길이 상한. 모델이 속으로 생각하는 몫도 여기에 들어간다
NOTE_MAX_TOKENS = 5000            # 요약 노트(호출 5)의 답 길이 상한
