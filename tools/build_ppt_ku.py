# -*- coding: utf-8 -*-
"""RTAB-Map 재위치추정 실험 슬라이드 → 고려대 랩미팅 양식 PowerPoint.

양식 출처: manipulator_ppt/build2.js (2026-08 랩미팅 덱)
  - 상/하단 크림슨 바, 좌상단 번호 배지, 우상단 로고, 하단 푸터
  - 슬라이드 13.333 x 7.5 in, 콘텐츠는 y 6.9 in 아래로 내려가지 않게 할 것
"""
import re, os
from pptx import Presentation
from pptx.util import Emu, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.oxml.ns import qn

SRC = "/Users/paddone/limo-lab/3d map/slides"
OUT = os.path.join(SRC, "rtabmap-reliability-ku.pptx")

# 원본 캔버스가 1280x720 px = 13.333 x 7.5 in (96 dpi) 이라 px 를 그대로 쓴다.
PX = 9525
IN = 96.0                      # build2.js 의 inch 좌표 -> px
def E(px): return Emu(int(round(px * PX)))
def S(px): return Pt(px * 0.75)          # CSS px -> pt

FONT = "Apple SD Gothic Neo"
LAB = "Field Robotics Lab"

# ---- build2.js 팔레트 ----
CRIMSON = RGBColor(0x8A, 0x15, 0x38)
DARK    = RGBColor(0x22, 0x24, 0x28)
GRAY    = RGBColor(0x8A, 0x8A, 0x90)
BODY    = RGBColor(0x3D, 0x3F, 0x45)
LINE    = RGBColor(0xD9, 0xDA, 0xDE)
SOFT    = RGBColor(0xF6, 0xF6, 0xF8)
WHITE   = RGBColor(0xFF, 0xFF, 0xFF)
BORDER  = RGBColor(0xC9, 0xCB, 0xD1)
# 같은 덱의 4유형 색 — 의미별 강조에 재사용
NAVY   , T_NAVY   = RGBColor(0x2F,0x3C,0x7E), RGBColor(0xDE,0xE2,0xF0)
TEAL   , T_TEAL   = RGBColor(0x1C,0x72,0x93), RGBColor(0xDC,0xEB,0xF1)
ORANGE , T_ORANGE = RGBColor(0xC9,0x6A,0x22), RGBColor(0xF8,0xE7,0xD8)
GREEN  , T_GREEN  = RGBColor(0x2E,0x7D,0x52), RGBColor(0xE4,0xF1,0xEA)
T_CRIM            = RGBColor(0xFB,0xF2,0xF4)
T_FAIL            = RGBColor(0xF8,0xE1,0xDE)

prs = Presentation()
prs.slide_width, prs.slide_height = E(1280), E(720)
BLANK = prs.slide_layouts[6]


# ───────────────────────── 텍스트 유틸 ─────────────────────────
def _runs(p, markup, size, color, bold, accent):
    """<b>굵게</b>, <hi>강조색+굵게</hi> 두 가지 인라인 태그를 푼다."""
    for seg in re.split(r"(<b>.*?</b>|<hi>.*?</hi>)", markup.replace("&nbsp;", " ")):
        if not seg:
            continue
        mb = re.fullmatch(r"<b>(.*?)</b>", seg, re.S)
        mh = re.fullmatch(r"<hi>(.*?)</hi>", seg, re.S)
        r = p.add_run()
        r.text = (mb or mh).group(1) if (mb or mh) else seg
        f = r.font
        f.name, f.size = FONT, S(size)
        f.color.rgb = accent if mh else color
        f.bold = True if (mb or mh) else bold


def emit(tf, markup, size, color, *, bold=False, ls=1.35, align=PP_ALIGN.LEFT,
         accent=CRIMSON, space_before=0):
    first = True
    for line in markup.split("<br>"):
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.alignment, p.line_spacing = align, ls
        p.space_before = Pt(space_before if not first else 0)
        _runs(p, line, size, color, bold, accent)


def text(sl, x, y, w, h, markup, size, color, *, pt=None, anchor=MSO_ANCHOR.TOP, **kw):
    """pt 를 주면 px 대신 pt 를 직접 지정 (양식 크롬용)."""
    tb = sl.shapes.add_textbox(E(x), E(y), E(w), E(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    emit(tf, markup, (pt / 0.75) if pt else size, color, **kw)
    return tb


def para(tf, markup, size, color, *, bold=False, ls=1.35, before=0, first=False,
         accent=CRIMSON, align=PP_ALIGN.LEFT):
    p = tf.paragraphs[0] if first else tf.add_paragraph()
    p.line_spacing, p.space_before, p.alignment = ls, Pt(before), align
    _runs(p, markup, size, color, bold, accent)


def charspace(tb, pt_val):
    """자간(letter-spacing). python-pptx API 에 없어 rPr@spc 를 직접 넣는다 (1/100 pt)."""
    for p in tb.text_frame.paragraphs:
        for r in p.runs:
            r._r.get_or_add_rPr().set('spc', str(int(pt_val * 100)))


# ───────────────────────── 도형 유틸 ─────────────────────────
def rect(sl, x, y, w, h, fill, line=None, lw=0.75):
    sh = sl.shapes.add_shape(MSO_SHAPE.RECTANGLE, E(x), E(y), E(w), E(h))
    sh.fill.solid(); sh.fill.fore_color.rgb = fill
    if line is None:
        sh.line.fill.background()
    else:
        sh.line.color.rgb = line; sh.line.width = Pt(lw)
    sh.shadow.inherit = False
    return sh


def box(sl, x, y, w, h, fill, border, radius=12, lw=1.0):
    sh = sl.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, E(x), E(y), E(w), E(h))
    sh.adjustments[0] = radius / min(w, h)
    sh.fill.solid(); sh.fill.fore_color.rgb = fill
    if border is None:
        sh.line.fill.background()
    else:
        sh.line.color.rgb = border; sh.line.width = Pt(lw)
    sh.shadow.inherit = False
    return sh


def inner(sh, pad_l=20, pad_t=15, anchor=MSO_ANCHOR.TOP):
    tf = sh.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = E(pad_l)
    tf.margin_top = tf.margin_bottom = E(pad_t)
    tf.vertical_anchor = anchor
    return tf


def pic(sl, x, y, w, h, name, border=True):
    p = sl.shapes.add_picture(os.path.join(SRC, name), E(x), E(y), E(w), E(h))
    if border:
        p.line.color.rgb = LINE; p.line.width = Pt(0.75)
    return p


def fit(w_box, h_box, iw, ih):
    """build2.js 의 img() 와 같은 contain 계산 — 비율을 절대 깨지 않는다."""
    ar = iw / ih
    w, h = w_box, w_box / ar
    if h > h_box:
        h, w = h_box, h_box * ar
    return w, h


# ───────────────────── 양식 크롬 (build2.js 이식) ─────────────────────
def bars(sl):
    rect(sl, 0, 0, 1280, 0.07 * IN, CRIMSON)
    rect(sl, 0, 7.43 * IN, 1280, 0.07 * IN, CRIMSON)


def logo(sl, x, y, h):
    sl.shapes.add_picture(os.path.join(SRC, "logo.png"),
                          E(x), E(y), E(h * (180 / 211)), E(h))


def header(sl, num, title):
    b = rect(sl, 0.55 * IN, 0.30 * IN, 0.42 * IN, 0.42 * IN, CRIMSON)
    tf = b.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    emit(tf, num, 13 / 0.75, WHITE, bold=True, align=PP_ALIGN.CENTER, ls=1.0)
    text(sl, 1.12 * IN, 0.30 * IN, 10.4 * IN, 0.42 * IN, title, None, DARK,
         pt=18.5, bold=True, anchor=MSO_ANCHOR.MIDDLE, ls=1.0)
    logo(sl, 12.24 * IN, 0.16 * IN, 0.62 * IN)
    rect(sl, 0.55 * IN, 0.86 * IN, 12.23 * IN, 1, LINE)


def keymsg(sl, markup):
    sh = box(sl, 0.55 * IN, 1.00 * IN, 12.23 * IN, 0.42 * IN, WHITE, BORDER, radius=2)
    tf = sh.text_frame
    tf.margin_left = tf.margin_right = E(16)
    tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    emit(tf, markup, 12 / 0.75, DARK, align=PP_ALIGN.CENTER, ls=1.0)


def footer(sl, sources, page):
    if sources:
        text(sl, 0.55 * IN, 7.12 * IN, 9.7 * IN, 0.26 * IN, sources, None, GRAY,
             pt=8, anchor=MSO_ANCHOR.MIDDLE, ls=1.0)
    text(sl, 10.4 * IN, 7.12 * IN, 2.38 * IN, 0.26 * IN,
         f"{LAB}  |  {page:02d}", None, GRAY,
         pt=8, align=PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.MIDDLE, ls=1.0)


def chrome(num, title, key, sources, page):
    sl = prs.slides.add_slide(BLANK)
    bars(sl); header(sl, num, title); keymsg(sl, key); footer(sl, sources, page)
    return sl


# 콘텐츠 영역: keymsg 아래 ~ 푸터 위 (README: y 6.9 in 아래로 내려가지 않게)
TOP, BOT = 150, int(6.9 * IN)          # 150 .. 662
GUT, X0, XW = 28, int(0.55 * IN), int(12.23 * IN)   # 52 .. 1226


# ══════════════════════════ S1 표지 ══════════════════════════
s = prs.slides.add_slide(BLANK)
bars(s)
logo(s, 0.62 * IN, 0.48 * IN, 1.05 * IN)
tb = text(s, 0.9 * IN, 2.62 * IN, 11.0 * IN, 0.32 * IN,
          "LAB MEETING  ·  EXPERIMENT REPORT", None, CRIMSON, pt=11.5, bold=True, ls=1.0)
charspace(tb, 2.5)
text(s, 0.88 * IN, 3.02 * IN, 11.6 * IN, 0.75 * IN,
     "카메라 SLAM 지도의 재위치추정 신뢰도 측정", None, DARK, pt=32, bold=True, ls=1.0)
text(s, 0.9 * IN, 3.86 * IN, 11.6 * IN, 0.40 * IN,
     "만든 지도를 언제까지 믿을 수 있나  —  조도·배치 변화에 대한 성공률 실측",
     None, BODY, pt=13.5, ls=1.0)
rect(s, 0.9 * IN, 4.55 * IN, 1.15 * IN, 2, CRIMSON)
text(s, 0.9 * IN, 4.80 * IN, 6.0 * IN, 0.62 * IN,
     "발표자: 박준혁 (Field Robot Lab)<br>2026. 09. 02.", None, BODY, pt=11.5, ls=1.3)
text(s, 0.9 * IN, 6.78 * IN, 11.6 * IN, 0.30 * IN,
     "LIMO Pro + Orbbec RGB-D · 카메라 전용 RTAB-Map · 2026.08.30 ~ 09.02 · 5개 지점 × 2개 조도 조건 27회 시행",
     None, GRAY, pt=9.5, ls=1.0)


# ═════════════════════ S2 · 과제와 측정 방법 ═════════════════════
s = chrome("01", "과제와 측정 방법",
           "만든 지도를 <hi>언제까지 믿을 수 있나</hi>  —  정답은 바닥 테이프, 판정은 0.5 m · 30°",
           "측정: auto_trial.py 자동 기록 (수렴 시각 · 오차 · 믿음 점프)", 2)

LW, RW = 620, XW - 620 - GUT              # 620 / 578
RX = X0 + LW + GUT

b = box(s, X0, TOP, LW, 310, T_NAVY, NAVY)
tf = inner(b, 20, 16, MSO_ANCHOR.MIDDLE)
para(tf, "측정 방법", 18, NAVY, bold=True, first=True)
for line in [
    "<b>지도 1회 고정</b> — 매핑 후 원본 DB 읽기 전용 보관, 측정은 매회 사본으로 (cold start)",
    "<b>정답 = 바닥 테이프</b> — 지점마다 위치·방향 테이프 등록, 시스템 출력과 독립된 기준",
    "<b>판정 허용치</b> — 위치 0.5 m · 방향 30° 이내면 성공, 벗어나면 오탐, 미발행이면 미수렴",
    "<b>2단계 프로토콜</b> — 정지 20초 → 미수렴 시 저속 회전, 총 60초",
    "<b>반복</b> — 지점 × 조건당 3회, 스크립트 자동 기록",
]:
    para(tf, line, 15, BODY, ls=1.45, before=10)

b = box(s, X0, TOP + 322, LW, 190, T_TEAL, TEAL)
tf = inner(b, 20, 14, MSO_ANCHOR.MIDDLE)
para(tf, "조건 (조도 중심)", 18, TEAL, bold=True, first=True)
para(tf, "<b>C1</b> 기준 — 주간 · 조명 켬 (매핑과 동일)", 15, BODY, ls=1.5, before=9)
para(tf, "<b>C3</b> 소등 — 주간 · 조명 전체 소등 (창측 자연광 잔존)", 15, BODY, ls=1.5)
para(tf, "※ 시간대·배치 조건은 지도교수 지침에 따라 조도 조건으로 통합", 13.5, GRAY, ls=1.5)

iw, ih = fit(RW, 340, 720, 411)
pic(s, RX + (RW - iw) / 2, TOP + 60, iw, ih, "points_map.jpg")
text(s, RX, TOP + 60 + ih + 12, RW, 44,
     "측정 지점 7곳 테이프 등록 (강의실 P1·P2·P3·P7, 복도 P4·P5·P6)<br>이 중 <b>P1·P2·P4·P5·P7</b> 5곳 실측",
     14, GRAY, align=PP_ALIGN.CENTER, ls=1.4)


# ═════════════════════════ S3 · 결과 ═════════════════════════
s = chrome("02", "측정 결과",
           "소등해도 성공률은 같다  —  <hi>C1 42%  ≈  C3 40%</hi>",
           "성공 = 60초 내 테이프 정답 대비 0.5 m · 30° 이내 수렴 · *P5 C1은 카메라 고장·배터리로 미측정", 3)

LW, RW = 690, XW - 690 - GUT              # 690 / 508
RX = X0 + LW + GUT

rows = [
    ("지점", "C1 기준 (불 켬)", "C3 소등 (주간)", "특성", None),
    ("<b>P1</b> 강의실 중앙", "<b>3/3</b> (0.5s · 3cm)", "<b>3/3</b> (0.6s · 8cm)", "기준값 — 안정", ('g', 'g')),
    ("<b>P2</b> 창문 벽", "0/3", "1/3 (즉시 · 2cm)", "특징점 빈곤", ('r', None)),
    ("<b>P4</b> 복도 초입", "1/3 (즉시 · 13cm)", "1/3 (즉시 · 7cm)", "확률적", (None, None)),
    ("<b>P5</b> 복도 중간", "미측정*", "1/3 (즉시 · 6cm)", "확률적", (None, None)),
    ("<b>P7</b> 북쪽 경계", "1/3 (즉시 · 9cm)", "0/3", "오인 다발", (None, 'r')),
    ("<b>전체</b>", "<b>5/12 (42%)</b>", "<b>6/15 (40%)</b>", "—", (None, None)),
]
TW, RH = [198, 183, 176, 133], 46
gt = s.shapes.add_table(len(rows), 4, E(X0), E(TOP), E(LW), E(RH * len(rows))).table
gt.first_row = False; gt.horz_banding = False
for i, w in enumerate(TW):
    gt.columns[i].width = E(w)
for ri, row in enumerate(rows):
    gt.rows[ri].height = E(RH)
    tint = row[4]
    for ci, md in enumerate(row[:4]):
        c = gt.cell(ri, ci)
        c.margin_left = c.margin_right = E(8)
        c.margin_top = c.margin_bottom = E(4)
        c.vertical_anchor = MSO_ANCHOR.MIDDLE
        c.fill.solid()
        if ri == 0:
            c.fill.fore_color.rgb = T_NAVY
        elif tint and ci in (1, 2) and tint[ci - 1]:
            c.fill.fore_color.rgb = T_GREEN if tint[ci - 1] == 'g' else T_FAIL
        else:
            c.fill.fore_color.rgb = WHITE
        emit(c.text_frame, md, 15, NAVY if ri == 0 else BODY,
             bold=(ri == 0), align=PP_ALIGN.CENTER, ls=1.1)

b = box(s, X0, TOP + RH * len(rows) + 20, LW, 128, T_CRIM, CRIMSON)
tf = inner(b, 20, 14)
para(tf, "성패를 가르는 것은 조명이 아니라 ① <b>지점의 특징점 품질</b> ② <b>cold start 확률성</b> "
         "(성공은 대부분 기동 직후 정지 상태에서, 회전 중엔 모션 블러로 실패) ③ <b>시각적 혼동</b>",
     15, BODY, ls=1.5, first=True)

iw, ih = fit(RW, 225, 520, 390)
for k, (fn, cap) in enumerate([
        ("p2fail.jpg",   "P2 카메라 시점 — 흰 벽·흰 가전뿐, 잡을 특징점이 없다"),
        ("lightsoff.jpg", "C3 소등 상태의 카메라 시점 — 자연광 + 자동 노출로 장면 유지")]):
    y = TOP + k * (ih + 34)
    pic(s, RX + (RW - iw) / 2, y, iw, ih, fn)
    text(s, RX, y + ih + 6, RW, 24, cap, 13.5, GRAY, align=PP_ALIGN.CENTER, ls=1.2)


# ═══════════════════ S4 · 실패 지점 분석 ═══════════════════
s = chrome("03", "실패 지점 분석",
           "실패는 무작위가 아니라 <hi>특정 지점에 몰린다</hi>  —  P1↔P7 오인 4회 재현",
           "지점별 성공률은 C1 · C3 합산 · 오인 검출은 /localization_pose 점프 자동 기록", 4)

LW, RW = 650, XW - 650 - GUT              # 650 / 548
RX = X0 + LW + GUT

iw, ih = fit(LW, 380, 720, 411)
pic(s, X0 + (LW - iw) / 2, TOP, iw, ih, "fail_map.jpg")
tb = s.shapes.add_textbox(E(X0), E(TOP + ih + 10), E(LW), E(26))
tf = tb.text_frame; tf.word_wrap = True
tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER; p.line_spacing = 1.2
for txt, col, bd in [("지점별 성공률 (C1+C3 합산) — ", GRAY, False), ("초록", GREEN, True),
                     (" 안정 · ", GRAY, False), ("빨강", CRIMSON, True),
                     (" 취약 · 회색 미측정", GRAY, False)]:
    r = p.add_run(); r.text = txt
    r.font.name, r.font.size, r.font.color.rgb, r.font.bold = FONT, S(14), col, bd

b = box(s, RX, TOP, RW, 165, T_CRIM, CRIMSON)
tf = inner(b, 20, 15)
para(tf, "시각적 혼동 (perceptual aliasing)", 17, CRIMSON, bold=True, first=True)
para(tf, "P1↔P7 오인이 <b>양방향으로 4회</b> 재현됨. 책상 반복 무늬가 두 지점에서 비슷하게 보여, "
         "로봇이 P7에 서서 “나는 P1”이라 믿는 식의 <b>4 m급 믿음 점프</b>가 기록됨 (전부 자동 검출).",
     15, BODY, ls=1.5, before=9)

b = box(s, RX, TOP + 177, RW, 150, T_ORANGE, ORANGE)
tf = inner(b, 20, 15)
para(tf, "취약 지점의 공통점", 17, ORANGE, bold=True, first=True)
para(tf, "<b>P2</b> 흰 벽·가전 — 특징점 빈곤 (회전 스윕에도 미수렴)", 15, BODY, ls=1.5, before=9)
para(tf, "<b>P7</b> 개활 구역 — 반복 무늬 + 관측 부족 방향", 15, BODY, ls=1.5)
para(tf, "<b>P4·P5</b> 복도 — 첫 회차만 성공하는 확률성", 15, BODY, ls=1.5)

b = box(s, RX, TOP + 339, RW, 135, SOFT, LINE)
tf = inner(b, 20, 15)
para(tf, "오탐(엉뚱한 곳으로 수렴) 방지를 위해 매칭 문턱을 올린 상태 (MinInliers 20→30). "
         "오인은 줄었지만 어려운 지점의 성공률이 함께 낮아짐 — <b>정확도와 가용성의 트레이드오프</b>를 그대로 보고.",
     15, BODY, ls=1.5, first=True)


# ═══════════════════════ S5 · 결론 ═══════════════════════
s = chrome("04", "결론과 운영 시사점",
           "지도의 유효기간은 시간이 아니라 <hi>“배치가 유지되는 동안”</hi>",
           "의자 사건: 2026-09-02 오전 P1 · 전날 대비 조명·지점 동일, 가구 배치만 변화", 5)

LW, RW = 610, XW - 610 - GUT              # 610 / 588
RX = X0 + LW + GUT

b = box(s, X0, TOP, LW, 270, T_NAVY, NAVY)
tf = inner(b, 20, 15)
para(tf, "실증 사례 — 의자 사건 (9/2 오전)", 17, NAVY, bold=True, first=True)
para(tf, "<b>9/1</b>&nbsp;&nbsp;기준 지점 P1, 3회 연속 즉시 수렴 (오차 3 cm)", 15, BODY, ls=1.45, before=10)
para(tf, "<b>9/2 오전</b>&nbsp;&nbsp;밤사이 의자들이 <b>수십 cm씩만</b> 이동", 15, BODY, ls=1.45, before=8)
para(tf, "<b>→</b>&nbsp;&nbsp;같은 지점·같은 조명에서 <b>2회 연속 미수렴</b>.", 15, BODY, ls=1.45, before=8)
para(tf, "     후보 매칭은 되지만 실물이 달라 기하검증 전멸", 15, BODY, ls=1.45)
para(tf, "<b>→</b>&nbsp;&nbsp;<b>5분 이어매핑</b>으로 지도 갱신 후 0.4초 만에 수렴 복구", 15, BODY, ls=1.45, before=8)

b = box(s, X0, TOP + 282, LW, 210, T_GREEN, GREEN)
tf = inner(b, 20, 15)
para(tf, "운영 시사점", 17, GREEN, bold=True, first=True)
para(tf, "① 조도 변화(주간 소등)에는 강하다 — 성공률 동일", 15, BODY, ls=1.55, before=9)
para(tf, "② 가구 배치 변화에는 약하다 — “살짝”으로도 기준 지점 상실", 15, BODY, ls=1.55)
para(tf, "③ 복구는 저렴하다 — 재매핑이 아니라 <b>5분 이어매핑</b>이면 충분", 15, BODY, ls=1.55)
para(tf, "④ 기하(형상) 기반 LiDAR+AMCL에는 없는 유형의 실패로 추정", 15, BODY, ls=1.55)
para(tf, "     → 동일 지점 직접 비교는 향후 과제", 15, BODY, ls=1.55)

iw, ih = fit(RW, 400, 520, 390)
pic(s, RX + (RW - iw) / 2, TOP, iw, ih, "chair.jpg")
text(s, RX, TOP + ih + 12, RW, 50,
     "미수렴 당시 로봇 시점(P1) — 근거리 의자가 시야를 지배.<br>사람 눈에는 “거의 그대로”인 배치가 카메라에는 다른 장소",
     14, GRAY, align=PP_ALIGN.CENTER, ls=1.4)


prs.save(OUT)
print("saved:", OUT, os.path.getsize(OUT), "bytes")
