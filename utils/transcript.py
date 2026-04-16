"""
transcript.py
유튜브 자막을 가져오고, 문장 단위로 합쳐주는 유틸리티 모듈

자막이 없는 영상은 Whisper AI 음성인식으로 자동 생성합니다.
"""

import os
import re
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)



# ──────────────────────────────────────────────
# 1. 유튜브 URL → 비디오 ID 추출
# ──────────────────────────────────────────────

def extract_video_id(url: str) -> str | None:
    """
    다양한 형식의 유튜브 URL에서 11자리 비디오 ID를 추출합니다.

    지원 형식:
      - https://www.youtube.com/watch?v=XXXXXXXXXXX
      - https://youtu.be/XXXXXXXXXXX
      - https://www.youtube.com/embed/XXXXXXXXXXX
      - https://www.youtube.com/shorts/XXXXXXXXXXX

    반환값: 비디오 ID 문자열, 없으면 None
    """
    patterns = [
        r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})",
        r"youtube\.com/embed/([a-zA-Z0-9_-]{11})",
        r"youtube\.com/shorts/([a-zA-Z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


# ──────────────────────────────────────────────
# 2. 유튜브에서 자막 가져오기
# ──────────────────────────────────────────────

def get_transcript(video_id: str, language: str = "en", assemblyai_key: str = "") -> tuple[list | None, str]:
    """
    유튜브 자막 API를 호출하여 자막을 가져옵니다.

    매개변수:
      video_id : 유튜브 비디오 ID
      language : 원하는 자막 언어 코드 (예: 'en', 'ko')

    반환값:
      (자막 리스트, 메시지 문자열)
      자막 리스트는 [{'text': ..., 'start': ..., 'duration': ...}, ...] 형태
      실패 시 (None, 오류 메시지)
    """
    try:
        # youtube-transcript-api 1.x: 클래스를 인스턴스로 만들어서 사용
        api = YouTubeTranscriptApi()

        # 해당 영상의 자막 목록을 가져옵니다 (1.x: list_transcripts → list)
        transcript_list = api.list(video_id)

        transcript = None

        # ① 요청한 언어의 수동 자막 시도
        try:
            transcript = transcript_list.find_manually_created_transcript([language])
        except NoTranscriptFound:
            pass

        # ② 요청한 언어의 자동 생성 자막 시도
        if transcript is None:
            try:
                transcript = transcript_list.find_generated_transcript([language])
            except NoTranscriptFound:
                pass

        # ③ 영어 자막으로 대체
        if transcript is None:
            try:
                transcript = transcript_list.find_transcript(["en"])
                language = "en"
            except NoTranscriptFound:
                pass

        # ④ 어떤 자막이든 첫 번째 것 사용
        if transcript is None:
            available = list(transcript_list)
            if available:
                transcript = available[0]
            else:
                return None, "이 영상에는 사용 가능한 자막이 없습니다."

        # 자막 데이터를 가져와서 딕셔너리 리스트로 변환
        # 1.x: transcript.fetch() → FetchedTranscript (iterable)
        raw_data = transcript.fetch()
        items = _to_dict_list(raw_data)

        # 짧은 조각들을 문장 단위로 합칩니다
        sentences = merge_sentences(items)

        return sentences, f"자막 언어: {transcript.language} ({transcript.language_code})"

    except VideoUnavailable:
        return None, "영상을 찾을 수 없습니다. URL을 확인해 주세요."
    except TranscriptsDisabled:
        # 자막이 없으면 → AssemblyAI(클라우드) 또는 Whisper(로컬) 사용
        if assemblyai_key and assemblyai_key != "여기에_API_키_입력":
            return get_transcript_via_assemblyai(video_id, assemblyai_key)
        return get_transcript_via_whisper(video_id)
    except Exception as e:
        return None, f"알 수 없는 오류: {str(e)}"


# ──────────────────────────────────────────────
# 3-1. Whisper AI 음성인식 폴백 (자막이 없는 영상용)
# ──────────────────────────────────────────────

def get_transcript_via_whisper(video_id: str, model_size: str = "tiny") -> tuple[list | None, str]:
    """
    YouTube 자막이 없을 때 faster-whisper AI로 음성을 텍스트로 변환합니다.

    - faster-whisper 는 PyAV 내장 디코더를 사용해 시스템 ffmpeg 설치 불필요
    - 첫 실행 시 AI 모델을 자동 다운로드합니다 (tiny ≈ 75 MB)
    - CPU에서 1분짜리 영상 기준 약 15~30초 소요
    - model_size: "tiny" | "base" | "small" (클수록 정확하지만 느림)
    """
    try:
        from faster_whisper import WhisperModel
        import yt_dlp
        import tempfile
        import glob

        url = f"https://www.youtube.com/watch?v={video_id}"

        with tempfile.TemporaryDirectory() as tmpdir:
            audio_template = os.path.join(tmpdir, "audio.%(ext)s")

            # ① yt-dlp 로 오디오 다운로드 (포스트프로세서 없음 → ffprobe 불필요)
            ydl_opts = {
                "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio",
                "outtmpl": audio_template,
                "quiet": True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            # 다운로드된 파일 찾기 (확장자가 m4a, webm, opus 등 다양)
            downloaded = glob.glob(os.path.join(tmpdir, "audio.*"))
            if not downloaded:
                return None, "오디오 다운로드 실패"
            audio_file = downloaded[0]

            # ② faster-whisper 로 음성인식
            #    device="cpu", compute_type="int8" → 가벼운 CPU 모드
            model = WhisperModel(model_size, device="cpu", compute_type="int8")
            segments, _ = model.transcribe(audio_file)

            # ③ 세그먼트 → 딕셔너리 리스트 변환
            #    tempdir 삭제 전에 제너레이터를 완전히 소비해야 합니다
            items = [
                {
                    "text": seg.text.strip(),
                    "start": float(seg.start),
                    "duration": float(seg.end - seg.start),
                }
                for seg in segments
                if seg.text.strip()
            ]

        sentences = merge_sentences(items)
        return sentences, f"🤖 Whisper AI ({model_size} 모델)로 생성된 자막"

    except ImportError:
        return None, "faster-whisper 미설치: pip install faster-whisper yt-dlp"
    except Exception as e:
        msg = str(e)
        if "403" in msg or "Forbidden" in msg:
            return None, (
                "이 영상은 자막이 없고, 클라우드 서버에서는 YouTube 영상 다운로드가 차단됩니다.\n\n"
                "💡 해결 방법:\n"
                "• TED, BBC, CNN 등 자막이 있는 영상을 사용하세요.\n"
                "• 또는 내 컴퓨터에서 직접 실행하면 Whisper AI 음성인식이 동작합니다."
            )
        return None, f"Whisper 변환 실패: {msg}"


# ──────────────────────────────────────────────
# 3-2. AssemblyAI 클라우드 음성인식 (자막 없는 영상 + 클라우드 환경용)
# ──────────────────────────────────────────────

def get_transcript_via_assemblyai(video_id: str, api_key: str) -> tuple[list | None, str]:
    """
    AssemblyAI API로 YouTube 음성을 텍스트로 변환합니다.

    흐름:
      ① pytubefix 또는 yt-dlp 로 오디오 파일 다운로드
      ② AssemblyAI 업로드 엔드포인트에 파일 직접 업로드
      ③ AssemblyAI가 음성인식 처리
      ④ 문장 단위 결과 반환
    """
    import requests
    import time
    import tempfile
    import glob

    yt_url = f"https://www.youtube.com/watch?v={video_id}"
    auth_headers = {"authorization": api_key}

    with tempfile.TemporaryDirectory() as tmpdir:

        # ① 오디오 다운로드 (pytubefix 우선, yt-dlp 폴백)
        audio_file = None

        try:
            from pytubefix import YouTube
            yt = YouTube(yt_url, use_oauth=False, allow_oauth_cache=False)
            stream = yt.streams.filter(only_audio=True).order_by("abr").last()
            if stream:
                audio_file = stream.download(output_path=tmpdir, filename="audio")
        except Exception:
            pass

        if not audio_file or not os.path.exists(audio_file):
            try:
                import yt_dlp
                tpl = os.path.join(tmpdir, "audio.%(ext)s")
                ydl_opts = {
                    "format": "bestaudio[ext=m4a]/bestaudio",
                    "outtmpl": tpl,
                    "quiet": True,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([yt_url])
                files = glob.glob(os.path.join(tmpdir, "audio.*"))
                if files:
                    audio_file = files[0]
            except Exception as e:
                return None, f"오디오 다운로드 실패: {str(e)}"

        if not audio_file or not os.path.exists(audio_file):
            return None, "오디오 파일을 다운로드할 수 없습니다. 클라우드 서버에서 YouTube가 차단될 수 있습니다."

        # ② AssemblyAI에 파일 직접 업로드
        try:
            with open(audio_file, "rb") as f:
                upload_resp = requests.post(
                    "https://api.assemblyai.com/v2/upload",
                    headers={"authorization": api_key},
                    data=f,
                    timeout=120,
                )
            upload_resp.raise_for_status()
            upload_url = upload_resp.json()["upload_url"]
        except Exception as e:
            return None, f"AssemblyAI 업로드 실패: {str(e)}"

    # ③ 트랜스크립션 요청
    try:
        json_headers = {**auth_headers, "content-type": "application/json"}
        resp = requests.post(
            "https://api.assemblyai.com/v2/transcript",
            json={"audio_url": upload_url, "language_detection": True},
            headers=json_headers,
            timeout=30,
        )
        resp.raise_for_status()
        transcript_id = resp.json()["id"]
    except Exception as e:
        return None, f"AssemblyAI 요청 실패: {str(e)}"

    # ④ 완료될 때까지 폴링 (5초 간격, 최대 10분)
    for _ in range(120):
        time.sleep(5)
        result = requests.get(
            f"https://api.assemblyai.com/v2/transcript/{transcript_id}",
            headers=auth_headers, timeout=15,
        ).json()
        if result["status"] == "completed":
            break
        elif result["status"] == "error":
            return None, f"AssemblyAI 변환 오류: {result.get('error', '알 수 없는 오류')}"
    else:
        return None, "시간 초과: 변환이 10분을 넘겼습니다."

    # ⑤ 문장 단위 결과 가져오기
    try:
        sent_resp = requests.get(
            f"https://api.assemblyai.com/v2/transcript/{transcript_id}/sentences",
            headers=auth_headers, timeout=15,
        ).json()
        items = [
            {
                "text": s["text"],
                "start": s["start"] / 1000.0,
                "duration": (s["end"] - s["start"]) / 1000.0,
            }
            for s in sent_resp.get("sentences", [])
            if s.get("text", "").strip()
        ]
    except Exception:
        items = []

    if not items and result.get("text"):
        items = merge_sentences([{"text": result["text"], "start": 0.0, "duration": 0.0}])

    return items, "☁️ AssemblyAI로 생성된 자막"


def _to_dict_list(raw_data) -> list:
    """
    youtube-transcript-api 버전에 따라 반환 형태가 다를 수 있어서
    안전하게 딕셔너리 리스트로 통일합니다.
    """
    result = []
    for item in raw_data:
        try:
            # 딕셔너리 형태 (구버전 API)
            result.append({
                "text": item["text"],
                "start": float(item["start"]),
                "duration": float(item["duration"]),
            })
        except (TypeError, KeyError):
            # 객체 형태 (신버전 API)
            result.append({
                "text": item.text,
                "start": float(item.start),
                "duration": float(item.duration),
            })
    return result


# ──────────────────────────────────────────────
# 3. 자막 조각 → 문장 단위로 합치기
# ──────────────────────────────────────────────

def merge_sentences(items: list, max_chars: int = 180) -> list:
    """
    유튜브 자막은 짧은 조각으로 나뉘어 있어서,
    문장 부호(. ! ?) 기준으로 자연스러운 문장 단위로 합칩니다.

    매개변수:
      items     : [{'text': ..., 'start': ..., 'duration': ...}, ...] 리스트
      max_chars : 한 문장의 최대 글자 수 (이 이상이면 강제 분리)

    반환값: 합쳐진 문장 리스트
    """
    if not items:
        return []

    merged = []
    current_text = ""
    current_start = 0.0
    current_end = 0.0

    for item in items:
        text = item["text"].strip()

        # 자막에 포함된 개행 문자 제거
        text = text.replace("\n", " ").replace("\r", " ")

        if not text:
            continue

        if not current_text:
            # 새 문장 시작
            current_text = text
            current_start = item["start"]
            current_end = item["start"] + item["duration"]
        else:
            # 이어 붙이기
            current_text = current_text + " " + text
            current_end = item["start"] + item["duration"]

        # 문장 끝 판단 기준:
        # 1) 마침표·느낌표·물음표로 끝날 때
        # 2) 너무 길어졌을 때 (max_chars 초과)
        ends_sentence = bool(re.search(r'[.!?]["\')\]]?\s*$', current_text))
        too_long = len(current_text) > max_chars

        if ends_sentence or too_long:
            merged.append({
                "text": current_text.strip(),
                "start": current_start,
                "duration": current_end - current_start,
            })
            current_text = ""

    # 마지막에 남은 텍스트 처리
    if current_text.strip():
        merged.append({
            "text": current_text.strip(),
            "start": current_start,
            "duration": current_end - current_start,
        })

    return merged


# ──────────────────────────────────────────────
# 4. 초(seconds) → MM:SS 형식 변환 헬퍼
# ──────────────────────────────────────────────

def seconds_to_mmss(seconds: float) -> str:
    """123.4 → '02:03' 형식으로 변환"""
    total = int(seconds)
    m, s = divmod(total, 60)
    return f"{m:02d}:{s:02d}"
