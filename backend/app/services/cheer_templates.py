"""편집국이 짜둔 응원 문구.

자유 입력을 받지 않는 이유 — 이 서비스의 명부는 익명이다. 한 줄이라도
자유롭게 쓸 수 있게 하면 연락처·신원·비방이 흘러들 통로가 생기고, 그 순간
「이름과 꿈의 원문은 공유되지 않습니다」라는 약속이 깨진다.

문구만 고르게 하면 오가는 것은 번호뿐이다. 커뮤니티는 생기고 신원은 남지
않는다. 문구는 편집국의 목소리로 쓴다 — 따뜻하게, 지금 일어날 것처럼.

번호는 절대 재사용하지 않는다. 문구를 바꾸면 이미 보낸 응원의 뜻도 바뀐다.
"""

CHEER_TEMPLATES: dict[int, str] = {
    1: "그 아침, 저도 기다립니다",
    2: "같은 해에 저도 있습니다",
    3: "먼저 도착하시면 알려주세요",
    4: "그 자리가 잘 어울리실 겁니다",
    5: "오늘도 한 호 앞으로",
}


def is_valid(template_id: int) -> bool:
    return template_id in CHEER_TEMPLATES


def text_of(template_id: int) -> str:
    return CHEER_TEMPLATES.get(template_id, "")
