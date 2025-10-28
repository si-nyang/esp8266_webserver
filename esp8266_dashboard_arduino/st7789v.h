#ifndef ST7789V_DEFS
# define ST7789V_DEFS

// --- Screen ---
# define TFT_CS   15
# define TFT_RST  16
# define TFT_DC   2

// --- time url ---
# define GET_TIME_URL "http://172.20.10.2:5000/time"

// ── 화면/카드 레이아웃 ───────────────────────────────
# define W 320
# define H 240
# define MARGIN 8
# define CARD_X (MARGIN)
# define CARD_Y (MARGIN)
# define CARD_W (W - MARGIN*2)     // 304
# define CARD_H (H - MARGIN*2)     // 224
# define CARD_R 12

# define LEFT_W 120
# define RIGHT_X (CARD_X + LEFT_W)
# define RIGHT_W (CARD_W - LEFT_W)

// ── 간격 규칙(오른쪽 패널 전체 통일) ─────────────────
# define G_LABEL_TO_VALUE  20   // 라벨 baseline → 값 baseline
# define G_VALUE_TO_SEP    10   // 값 baseline → 구분선
# define G_SEP_TO_LABEL    18   // 구분선 → 다음 섹션 라벨 baseline
# define G_ROW             24   // 같은 섹션 내 행 간격(값↔값)

#endif