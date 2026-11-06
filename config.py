# -*- coding: utf-8 -*-
"""빈틈노트 설정. 숫자와 이름은 여기 한 곳에서만 바꾼다."""

LLM_MODEL = "claude-sonnet-5-5"   # 이 한 줄만 바꾸면 언어 모델 교체 (예: "claude-haiku-5-5")
STT_MODEL = "whisper-1"           # None이면 음성 인식 끄기(대본 붙여넣기만 사용)
N_DIAG_DEFAULT = 5                # 기본 진단 개념 수 (사이드바에서 3~8 조절)
MAX_PAGES = 120                   # 분석할 최대 쪽수
MAX_EVIDENCE_PAGES = 8            # 진단·설명 호출에 넣는 근거 쪽 상한
MAX_MATERIAL_MB = 30              # 강의자료 파일 크기 상한
MAX_AUDIO_MB = 25                 # 녹음 파일 크기 상한 (음성 인식 API 제한)
AUTO_EXPLAIN_TOP = 3              # S04에서 자동으로 설명을 만드는 개수
