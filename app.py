"""
app.py  ─  영어 쉐도잉 학습 웹 앱 (Streamlit)

실행 방법:
    streamlit run app.py
"""

import streamlit as st
import streamlit.components.v1 as components
from utils.transcript import get_transcript, extract_video_id, seconds_to_mmss

# ══════════════════════════════════════════════
# 페이지 기본 설정 (반드시 가장 먼저 호출)
# ══════════════════════════════════════════════
st.set_page_config(
    page_title="영어 쉐도잉 학습기",
    page_icon="🎤",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ══════════════════════════════════════════════
# CSS 스타일 (화면을 예쁘게 꾸밉니다)
# ══════════════════════════════════════════════
st.markdown(
    """
    <style>
    /* 현재 문장 박스 */
    .sentence-box {
        background: linear-gradient(135deg, #e8f4f8 0%, #d0eaf5 100%);
        border-left: 6px solid #1a73e8;
        padding: 22px 26px;
        border-radius: 12px;
        font-size: 1.35em;
        line-height: 1.8;
        min-height: 80px;
        margin-bottom: 12px;
        color: #1a1a2e;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    }

    /* 자막 목록 버튼 — 현재 선택된 항목 강조 */
    div[data-testid="stButton"] button.active-sentence {
        background-color: #fff3e0;
        border: 2px solid #ff9800;
    }

    /* 구간 표시 뱃지 */
    .time-badge {
        display: inline-block;
        background-color: #e3f2fd;
        color: #1565c0;
        border-radius: 6px;
        padding: 2px 8px;
        font-size: 0.85em;
        font-family: monospace;
        margin-right: 6px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ══════════════════════════════════════════════
# 세션 상태 초기화
# (Streamlit은 버튼 클릭 시 전체 스크립트를 다시 실행하므로
#  변수를 유지하려면 st.session_state를 사용합니다)
# ══════════════════════════════════════════════
defaults = {
    "transcript": None,    # 자막 리스트
    "video_id": None,      # 현재 영상 ID
    "current_index": 0,    # 현재 문장 인덱스
    "lang_info": "",       # 자막 언어 정보
}
for key, val in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = val


# ══════════════════════════════════════════════
# 사이드바
# ══════════════════════════════════════════════
with st.sidebar:
    st.markdown("## ⚙️ 설정")

    lang_option = st.selectbox(
        "자막 언어 선택",
        options=["en", "ko", "ja", "zh-Hans", "zh-Hant"],
        format_func=lambda x: {
            "en": "🇺🇸 영어 (English)",
            "ko": "🇰🇷 한국어",
            "ja": "🇯🇵 일본어",
            "zh-Hans": "🇨🇳 중국어(간체)",
            "zh-Hant": "🇹🇼 중국어(번체)",
        }[x],
        index=0,
        help="원하는 자막 언어를 선택하세요. 해당 언어 자막이 없으면 영어로 대체됩니다.",
    )

    st.markdown("---")
    st.markdown(
        """
        ### 📖 사용 방법
        1. YouTube URL을 입력하고 **Enter**
        2. 자막이 로드되면 문장 클릭
        3. **◀ 이전 / 다음 ▶** 으로 이동
        4. **🔄 다시 듣기** 로 반복 재생
        """
    )

    st.markdown("---")
    st.markdown(
        """
        ### 💡 추천 영상
        - TED Talks
        - BBC / CNN 뉴스
        - YouTube EDU 채널
        """
    )
    st.info("자막이 있는 영상이어야 합니다.")


# ══════════════════════════════════════════════
# 메인 화면 헤더
# ══════════════════════════════════════════════
st.title("🎤 영어 쉐도잉 학습기")
st.markdown("유튜브 영상 자막을 **한 문장씩** 반복 학습하세요!")
st.markdown("---")

# ══════════════════════════════════════════════
# URL 입력
# ══════════════════════════════════════════════
url_input = st.text_input(
    "🔗 YouTube URL을 입력하세요",
    placeholder="예) https://www.youtube.com/watch?v=JBGjE9_aosc",
    help="유튜브 영상 주소를 붙여넣은 뒤 Enter를 누르세요.",
)

# ══════════════════════════════════════════════
# URL 처리 & 자막 로드
# ══════════════════════════════════════════════
if url_input:
    video_id = extract_video_id(url_input)

    if not video_id:
        st.error("❌ 올바른 YouTube URL 형식이 아닙니다. 예: https://www.youtube.com/watch?v=XXXXXXXXXXX")
        st.stop()

    # 새 영상이면 자막을 새로 불러옵니다
    if st.session_state.video_id != video_id:
        # AssemblyAI API 키 읽기 (없으면 빈 문자열)
        assemblyai_key = st.secrets.get("assemblyai_api_key", "")

        with st.spinner("⏳ 자막을 불러오는 중... 자막이 없으면 AI 음성인식으로 자동 생성합니다 (최대 2~3분 소요)"):
            transcript, msg = get_transcript(video_id, lang_option, assemblyai_key)

        if transcript is None:
            st.error(f"❌ 자막 로드 실패: {msg}")
            st.stop()

        # 성공 → 세션 상태에 저장
        st.session_state.transcript = transcript
        st.session_state.video_id = video_id
        st.session_state.current_index = 0
        st.session_state.lang_info = msg

        if "Whisper" in msg:
            st.success(f"🤖 Whisper AI로 자막을 생성했습니다! 총 {len(transcript)}개 문장")
        else:
            st.success(f"✅ 총 {len(transcript)}개 문장을 불러왔습니다! ({msg})")

    # ── 자막 데이터 꺼내기 ──
    transcript = st.session_state.transcript
    idx = st.session_state.current_index
    total = len(transcript)
    current = transcript[idx]

    # ══════════════════════════════════════════
    # 화면 레이아웃: 왼쪽(플레이어) / 오른쪽(문장+컨트롤)
    # ══════════════════════════════════════════
    player_col, ctrl_col = st.columns([3, 2], gap="large")

    # ─── 왼쪽: 유튜브 임베드 플레이어 ───────────
    with player_col:
        st.markdown("### 📺 영상 플레이어")

        start_sec = int(current["start"])

        # autoplay=1 : 해당 위치에서 자동 재생
        # rel=0      : 관련 영상 표시 안 함
        youtube_embed = f"""
        <div style="position:relative; padding-bottom:56.25%; height:0; overflow:hidden; border-radius:12px; box-shadow:0 4px 16px rgba(0,0,0,0.15);">
            <iframe
                src="https://www.youtube.com/embed/{video_id}?start={start_sec}&autoplay=1&rel=0"
                style="position:absolute; top:0; left:0; width:100%; height:100%; border:none;"
                allow="autoplay; encrypted-media"
                allowfullscreen>
            </iframe>
        </div>
        """
        components.html(youtube_embed, height=390)

    # ─── 오른쪽: 현재 문장 + 컨트롤 ─────────────
    with ctrl_col:
        st.markdown("### 📝 현재 문장")

        # 시간 뱃지
        st.markdown(
            f'<span class="time-badge">⏱ {seconds_to_mmss(current["start"])}</span>'
            f"&nbsp; 문장 **{idx + 1}** / {total}",
            unsafe_allow_html=True,
        )

        # 문장 박스
        st.markdown(
            f'<div class="sentence-box">{current["text"]}</div>',
            unsafe_allow_html=True,
        )

        # 진행 바
        st.progress((idx + 1) / total)

        st.markdown("")  # 여백

        # ── 네비게이션 버튼 ──────────────────────
        btn_prev, btn_replay, btn_next = st.columns(3)

        with btn_prev:
            if st.button(
                "◀ 이전",
                use_container_width=True,
                disabled=(idx == 0),
                help="이전 문장으로 이동",
            ):
                st.session_state.current_index -= 1
                st.rerun()

        with btn_replay:
            if st.button(
                "🔄 다시",
                use_container_width=True,
                help="현재 문장을 처음부터 다시 재생",
            ):
                st.rerun()  # 같은 인덱스로 재실행 → iframe이 다시 로드됨

        with btn_next:
            if st.button(
                "다음 ▶",
                use_container_width=True,
                disabled=(idx == total - 1),
                help="다음 문장으로 이동",
            ):
                st.session_state.current_index += 1
                st.rerun()

        # ── 키보드 단축키 안내 ────────────────────
        st.markdown(
            """
            <small style="color:#888;">
            💡 팁: 이전/다음 버튼 클릭 후 영상이 해당 위치에서 자동 재생됩니다.
            </small>
            """,
            unsafe_allow_html=True,
        )

    # ══════════════════════════════════════════
    # 전체 자막 목록
    # ══════════════════════════════════════════
    st.markdown("---")
    st.markdown("### 📋 전체 자막 목록")
    st.markdown("문장을 클릭하면 해당 위치부터 재생됩니다.")

    # 현재 문장 주변을 기본으로 펼쳐 보여줍니다
    for i, item in enumerate(transcript):
        time_str = seconds_to_mmss(item["start"])
        # 현재 문장은 ▶ 표시, 나머지는 번호
        marker = "▶" if i == idx else f"{i + 1:>3}"
        # 긴 문장은 잘라서 표시
        preview = item["text"][:80] + ("…" if len(item["text"]) > 80 else "")
        label = f"{marker}  [{time_str}]  {preview}"

        if st.button(label, key=f"sent_{i}", use_container_width=True):
            st.session_state.current_index = i
            st.rerun()

# ══════════════════════════════════════════════
# URL 미입력 시 안내 화면
# ══════════════════════════════════════════════
else:
    st.markdown(
        """
        ### 👆 위에 YouTube URL을 입력하면 시작됩니다!

        ---

        #### 어떤 영상을 골라야 할까요?

        | 채널 유형 | 특징 | 난이도 |
        |---|---|---|
        | TED Talks | 명확한 발음, 다양한 주제 | ⭐⭐ |
        | BBC News | 영국식 영어, 시사 어휘 | ⭐⭐⭐ |
        | CNN News | 미국식 영어, 빠른 속도 | ⭐⭐⭐ |
        | Crash Course | 교육 콘텐츠, 친절한 설명 | ⭐⭐ |

        ---

        #### 쉐도잉이란?
        > 원어민의 말을 **그림자(shadow)** 처럼 따라 말하는 영어 학습법입니다.
        > 발음, 억양, 속도를 통째로 흉내 내는 것이 핵심입니다.
        """,
        unsafe_allow_html=False,
    )
