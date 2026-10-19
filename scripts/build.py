#!/usr/bin/env python3
"""Draws the pictures on github.com/roman-princ.

Each picture is an SVG in a dark and a light version, and the README picks one with <picture>. Its text is set as
Inter's outlines, each glyph drawn once and <use>d, so it reads the same on every machine. The motion is CSS, plus
SMIL for the plane. The contributions come from the public calendar, and .github/workflows/build.yml redraws
everything once a day.

    pip install fonttools uharfbuzz
    python scripts/build.py
"""

import base64
import datetime as dt
import html
import math
import os
import random
import re
import urllib.request

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.join(ROOT, "scripts")
OUT = os.path.join(ROOT, "assets")
USER = os.environ.get("GITHUB_USER", "roman-princ")
EASE = "cubic-bezier(.16,1,.3,1)"  # the portfolio's ease-out-expo


def num(v):
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


# ---------------------------------------------------------------------------------------------------------- type


class Face:
    """A font: shaped by HarfBuzz, each glyph's outline as path data in font units, y pointing down."""

    def __init__(self, key, file):
        path = os.path.join(HERE, "fonts", file)
        self.key = key
        self.tt = TTFont(path)
        self.glyphs = self.tt.getGlyphSet()
        self.upem = self.tt["head"].unitsPerEm
        self.hb = hb.Font(hb.Face(hb.Blob.from_file_path(path)))
        self.paths = {}

    def shape(self, s, features=None):
        if not s:
            return []
        buf = hb.Buffer()
        buf.add_str(s)
        buf.guess_segment_properties()
        hb.shape(self.hb, buf, features or {"kern": True, "liga": True})
        return [(i.codepoint, p.x_advance, p.x_offset, p.y_offset) for i, p in zip(buf.glyph_infos, buf.glyph_positions)]

    def outline(self, gid):
        if gid not in self.paths:
            pen = SVGPathPen(self.glyphs, ntos=lambda v: num(v))
            self.glyphs[self.tt.getGlyphName(gid)].draw(TransformPen(pen, (1, 0, 0, -1, 0, 0)))
            self.paths[gid] = pen.getCommands()
        return self.paths[gid]

    def width(self, s, size, track=0.0, features=None):
        run = self.shape(s, features)
        return (sum(a for _, a, _, _ in run) + track * self.upem * max(len(run) - 1, 0)) * size / self.upem


BOLD = Face("b", "InterDisplay-Bold.ttf")
SEMI = Face("s", "InterDisplay-SemiBold.ttf")
MED = Face("m", "Inter-Medium.ttf")
REG = Face("r", "Inter-Regular.ttf")
MONO = Face("j", "JetBrainsMono-Regular.ttf")
TNUM = {"kern": True, "tnum": True}
CAP = 0.7275  # Inter's cap height, in ems


def rows(face, s, size, width):
    """s broken into lines no wider than width."""
    out, line = [], ""
    for word in s.split():
        test = f"{line} {word}".strip()
        if line and face.width(test, size) > width:
            out.append(line)
            line = word
        else:
            line = test
    return out + [line]


# --------------------------------------------------------------------------------------------------------- pages

THEMES = {
    "dark": dict(card="#000000", edge="#ffffff1f", ink="#f5f5f7", muted="#86868b", dim="#5e5e63", line="#ffffff1f",
                 soft="#161618", inv="#f5f5f7", invink="#000000", win="#111112", bar="#1c1c1e", dots="#3a3a3d",
                 notif="#1c1c1ef2", notifedge="#ffffff1f", shadow=".6", cells=(.1, .32, .52, .76, 1)),
    "light": dict(card="#f5f5f7", edge="none", ink="#1d1d1f", muted="#6e6e73", dim="#8e8e93", line="#0000001a",
                  soft="#e8e8ed", inv="#1d1d1f", invink="#ffffff", win="#ffffff", bar="#ededf0", dots="#d1d1d6",
                  notif="#fffffff2", notifedge="#00000012", shadow=".18", cells=(.08, .28, .48, .72, 1)),
}

CSS = (
    f".u{{animation:up 1.1s {EASE} both}}@keyframes up{{from{{opacity:0;transform:translateY(16px)}}}}"
    f".u2{{animation:up2 1.6s {EASE} both}}@keyframes up2{{from{{opacity:0;transform:translateY(70px)}}}}"
    ".fade{animation:fade 1.2s ease both}@keyframes fade{from{opacity:0}}"
    f".ping{{transform-box:fill-box;transform-origin:center;animation:ping 2.4s {EASE} infinite}}"
    "@keyframes ping{0%{transform:scale(1);opacity:.6}100%{transform:scale(3.2);opacity:0}}"
    ".bob{animation:bob 6s ease-in-out infinite}@keyframes bob{50%{transform:translateY(-9px)}}"
    ".nudge{animation:nudge 4.5s ease-in-out infinite}"
    "@keyframes nudge{0%,78%,100%{transform:none}86%{transform:translate(2.5px,-2.5px)}}"
    "@media (prefers-reduced-motion:reduce){*{animation:none!important}.plane,.cv,.W~.W,.nt~.nt,.fr~.fr{display:none}}"
)


def anim(cls, delay, inner, extra=""):
    return f'<g class="{cls}" style="animation-delay:{delay:.2f}s"{extra}>{inner}</g>'


def media(name):
    with open(os.path.join(HERE, "media", name), "rb") as f:
        data = base64.b64encode(f.read()).decode()
    kind = "svg+xml" if name.endswith(".svg") else name.rsplit(".", 1)[1]
    return f"data:image/{kind};base64,{data}"


class Doc:
    """One picture in one theme: the glyphs it uses, its other defs and its styles."""

    def __init__(self, theme):
        self.theme, self.t = theme, THEMES[theme]
        self.glyphs, self.defs, self.css, self.n = {}, [], [CSS], 0

    def id(self, prefix="d"):
        self.n += 1
        return f"{prefix}{self.n}"

    def text(self, face, s, x, y, size, fill="ink", track=0.0, anchor="start", features=None, wrap=None):
        """s on the baseline y, from x (or centred on it, or ending at it): its markup and its width. wrap(i, use)
        wraps each glyph's <use>, for letters that move on their own."""
        run = face.shape(s, features)
        k = size / face.upem
        gap = track * face.upem
        width = (sum(a for _, a, _, _ in run) + gap * max(len(run) - 1, 0)) * k
        x -= {"start": 0, "middle": width / 2, "end": width}[anchor]
        uses, pen = [], 0.0
        for i, (gid, adv, dx, dy) in enumerate(run):
            d = face.outline(gid)
            if d:
                key = f"{face.key}{gid}"
                self.glyphs.setdefault(key, f'<path id="{key}" d="{d}"/>')
                use = f'<use href="#{key}" x="{num(pen + dx)}"' + (f' y="{num(-dy)}"' if dy else "") + "/>"
                uses.append(wrap(i, use) if wrap else use)
            pen += adv + gap
        fill = self.t.get(fill, fill)
        return f'<g transform="translate({num(x)} {num(y)}) scale({k:.5f})" fill="{fill}">{"".join(uses)}</g>', width

    def para(self, face, s, x, y, size, width, leading, fill="muted"):
        lines = rows(face, s, size, width)
        return "".join(self.text(face, line, x, y + i * leading, size, fill)[0] for i, line in enumerate(lines)), len(lines)

    def clip(self, x, y, w, h, r=0):
        cid = self.id("c")
        self.defs.append(f'<clipPath id="{cid}"><rect x="{num(x)}" y="{num(y)}" width="{num(w)}" height="{num(h)}" rx="{num(r)}"/></clipPath>')
        return cid

    def shadow(self, dy=18, blur=20, strength=1.0):
        fid = self.id("f")
        alpha = float(self.t["shadow"]) * strength
        self.defs.append(f'<filter id="{fid}" x="-30%" y="-30%" width="160%" height="170%" color-interpolation-filters="sRGB"><feDropShadow dx="0" dy="{dy}" '
                         f'stdDeviation="{blur}" flood-color="#000" flood-opacity="{alpha:.2f}"/></filter>')
        return fid

    def card(self, w, h, m=8, r=24):
        edge = "" if self.t["edge"] == "none" else f' stroke="{self.t["edge"]}"'
        return f'<rect x="{m + .5}" y="{m + .5}" width="{w - 2 * m - 1}" height="{num(h - 2 * m - 1)}" rx="{r}" fill="{self.t["card"]}"{edge}/>'

    def dot(self, cx, cy, r=4):
        c = self.t["ink"]
        return f'<circle class="ping" cx="{num(cx)}" cy="{num(cy)}" r="{r}" fill="{c}"/><circle cx="{num(cx)}" cy="{num(cy)}" r="{r}" fill="{c}"/>'

    def arrow(self, x, y, s, color, width=1.7):
        """↗, drawn: s wide, its top left corner at (x, y)."""
        return (f'<path d="M{num(x)} {num(y + s)}L{num(x + s)} {num(y)}M{num(x + s * .28)} {num(y)}H{num(x + s)}V{num(y + s * .72)}" '
                f'fill="none" stroke="{color}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round"/>')

    def svg(self, w, h, body, label):
        self.label = label
        label = html.escape(label)
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {num(w)} {num(h)}" width="{num(w)}" height="{num(h)}" '
                f'role="img" aria-label="{label}"><title>{label}</title><style>{"".join(self.css)}</style>'
                f'<defs>{"".join(self.glyphs.values())}{"".join(self.defs)}</defs>{body}</svg>')


# ------------------------------------------------------------------------------------------------------- devices

PLANE = ("M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 "
         "19v-5.5l8 2.5z")  # Material's "flight" (Apache 2.0), its nose up


def plane(cx, cy, size, fill, angle=90):
    return (f'<path transform="translate({num(cx)} {num(cy)}) rotate({angle}) scale({size / 24:.4f}) translate(-12 -12)" '
            f'd="{PLANE}" fill="{fill}"/>')


def macbook(doc, x, y, sw, ratio, href, image_class=""):
    """A MacBook from the front, its screen sw wide: the lid with its notch, the screen and the silver base."""
    b = sw * .022
    top = b * 1.25
    sh = sw / ratio
    lw, lh = sw + 2 * b, sh + b + top
    r, rb = lw * .03, lw * .008
    screen, silver = doc.id("c"), doc.id("g")
    doc.defs.append(f'<clipPath id="{screen}"><rect x="{num(x + b)}" y="{num(y + top)}" width="{num(sw)}" height="{num(sh)}" rx="{num(r * .3)}"/></clipPath>'
                    f'<linearGradient id="{silver}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ececef"/>'
                    f'<stop offset=".45" stop-color="#c2c2c7"/><stop offset="1" stop-color="#77777c"/></linearGradient>')
    lid = (f'M{num(x)} {num(y + r)}Q{num(x)} {num(y)} {num(x + r)} {num(y)}H{num(x + lw - r)}Q{num(x + lw)} {num(y)} {num(x + lw)} {num(y + r)}'
           f'V{num(y + lh - rb)}Q{num(x + lw)} {num(y + lh)} {num(x + lw - rb)} {num(y + lh)}H{num(x + rb)}Q{num(x)} {num(y + lh)} {num(x)} {num(y + lh - rb)}Z')
    nw, nh = sw * .1, top * .9
    bw, bh = lw * 1.13, lw * .024
    bx, by = x + lw / 2 - bw / 2, y + lh
    base = (f'M{num(bx)} {num(by)}H{num(bx + bw)}V{num(by + bh * .45)}Q{num(bx + bw)} {num(by + bh)} {num(bx + bw - bh * 2)} {num(by + bh)}'
            f'H{num(bx + bh * 2)}Q{num(bx)} {num(by + bh)} {num(bx)} {num(by + bh * .45)}Z')
    cls = f' class="{image_class}"' if image_class else ""
    return (f'<path d="{lid}" fill="#0e0e10" stroke="#46464b" stroke-width="1"/>'
            f'<g clip-path="url(#{screen})"><rect x="{num(x + b)}" y="{num(y + top)}" width="{num(sw)}" height="{num(sh)}" fill="#000"/>'
            f'<image{cls} href="{href}" x="{num(x + b)}" y="{num(y + top)}" width="{num(sw)}" height="{num(sh)}" preserveAspectRatio="xMidYMin slice"/></g>'
            f'<rect x="{num(x + lw / 2 - nw / 2)}" y="{num(y + top - 1)}" width="{num(nw)}" height="{num(nh)}" rx="{num(nh * .4)}" fill="#0e0e10"/>'
            f'<path d="{base}" fill="url(#{silver})"/>'
            f'<rect x="{num(x + lw / 2 - lw * .08)}" y="{num(by)}" width="{num(lw * .16)}" height="{num(bh * .36)}" rx="{num(bh * .18)}" fill="#8e8e93"/>')


def iphone(doc, x, y, w, href):
    """An iPhone, w wide (the portfolio's proportions): the titanium edge, the bezel, the screen and the Dynamic
    Island, a little larger than a simulator's so it covers one a screenshot already has. Its markup and height."""
    h = w * 149.6 / 71.5
    ring, bez = w * .011, w * .034
    inset = ring + bez
    sx, sy, sw, sh = x + inset, y + inset, w - 2 * inset, h - 2 * inset
    screen, ti = doc.id("c"), doc.id("g")
    doc.defs.append(f'<clipPath id="{screen}"><rect x="{num(sx)}" y="{num(sy)}" width="{num(sw)}" height="{num(sh)}" rx="{num(w * .112)}"/></clipPath>'
                    f'<linearGradient id="{ti}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#a1a1a6"/>'
                    f'<stop offset=".5" stop-color="#4d4d52"/><stop offset="1" stop-color="#8e8e93"/></linearGradient>')
    iw, ih = w * .275, w * .078
    return (f'<rect x="{num(x)}" y="{num(y)}" width="{num(w)}" height="{num(h)}" rx="{num(w * .155)}" fill="url(#{ti})"/>'
            f'<rect x="{num(x + ring)}" y="{num(y + ring)}" width="{num(w - 2 * ring)}" height="{num(h - 2 * ring)}" rx="{num(w * .144)}" fill="#000"/>'
            f'<g clip-path="url(#{screen})"><image href="{href}" x="{num(sx)}" y="{num(sy)}" width="{num(sw)}" height="{num(sh)}" preserveAspectRatio="xMidYMin slice"/></g>'
            f'<rect x="{num(x + w / 2 - iw / 2)}" y="{num(sy + w * .024)}" width="{num(iw)}" height="{num(ih)}" rx="{num(ih / 2)}" fill="#000"/>'), h


def window(doc, x, y, w, h, title):
    """A macOS window in greys: its frame, and a clip for what goes in it, under the title bar."""
    t = doc.t
    head = 24
    shape, inside = doc.clip(x, y, w, h, 10), doc.clip(x, y + head, w, h - head)
    sh = doc.shadow(12, 16, .8)
    dots = "".join(f'<circle cx="{x + 14 + i * 14}" cy="{y + 12}" r="4.2" fill="{t["dots"]}"/>' for i in range(3))
    name, _ = doc.text(MED, title, x + w / 2, y + 15.8, 10.5, "muted", anchor="middle")
    frame = (f'<g filter="url(#{sh})"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{t["win"]}"/></g>'
             f'<g clip-path="url(#{shape})"><rect x="{x}" y="{y}" width="{w}" height="{head}" fill="{t["bar"]}"/>'
             f'<rect x="{x}" y="{y + head - .5}" width="{w}" height=".5" fill="{t["line"]}"/></g>'
             f'<rect x="{x + .5}" y="{y + .5}" width="{w - 1}" height="{h - 1}" rx="9.5" fill="none" stroke="{t["line"]}"/>'
             f"{dots}{name}")
    return frame, inside, y + head


# ------------------------------------------------------------------------------------------------------ pictures

LETTERS_CSS = (f".L{{animation:rise 1.1s {EASE} both}}@keyframes rise{{from{{transform:translateY({BOLD.upem * 1.1:.0f}px)}}}}"
               ".ha,.hb{transform-box:fill-box;transform-origin:50% 100%;animation:ha 9s cubic-bezier(.3,0,.3,1) infinite}"
               ".hb{animation-name:hb}"
               "@keyframes ha{0%,5%,100%{transform:none}2.5%{transform:translateY(-12%) rotate(-6deg)}}"
               "@keyframes hb{0%,5%,100%{transform:none}2.5%{transform:translateY(-12%) rotate(6deg)}}")


def letters(doc, s, x, y, size, track, start, wave):
    """s in Inter Display Bold, its letters rising one after another through a mask and hopping in a wave every
    nine seconds, as the portfolio's do under the pointer."""
    def letter(i, use):
        hop = "ha" if i % 2 else "hb"
        return (f'<g class="L" style="animation-delay:{start + i * .05:.2f}s">'
                + use.replace("<use ", f'<use class="{hop}" style="animation-delay:{wave + i * .06:.2f}s" ', 1) + "</g>")
    doc.css.append(LETTERS_CSS)
    markup, width = doc.text(BOLD, s, x, y, size, "ink", track=track, wrap=letter)
    mask = doc.clip(0, y - size * 1.02, 1000, size * 1.28)
    return f'<g clip-path="url(#{mask})">{markup}</g>', width


def hero(doc):
    W, x0 = 1000, 56
    t = doc.t
    a, wa = doc.text(MED, "Available for freelance", x0 + 18, 80, 16, "ink")
    b, wb = doc.text(MED, "·", x0 + 18 + wa + 9, 80, 16, "dim")
    c, _ = doc.text(MED, "Prague, Czech Republic", x0 + 27 + wa + wb + 9, 80, 16, "muted")
    parts = [anim("u", .1, doc.dot(x0 + 4, 80 - 16 * CAP / 2) + a + b + c)]
    parts.append(anim("fade", .3, doc.text(BOLD, "rp.", W - x0, 81, 24, "ink", track=-.04, anchor="end")[0]))

    name, track = "Roman Princ.", -.045
    size = min(160, (W - 2 * x0 + 6) / BOLD.width(name, 1, track))
    base = 132 + size * CAP
    parts.append(letters(doc, name, x0 - size * .04, base, size, track, .25, 3.4)[0])

    # "I build …", the last words rolling through four things, as on the portfolio
    ss, tr = 38, -.022
    b1, b2 = base + 78, base + 126
    l1, _ = doc.text(SEMI, "Full-stack engineer.", x0, b1, ss, "muted", track=tr)
    l2, wi = doc.text(SEMI, "I build", x0, b2, ss, "muted", track=tr)
    wx = x0 + wi + SEMI.width(" ", ss)
    words, slot, roll = ["web apps", "mobile apps", "backends", "whole products"], 2.4, ss * 1.25
    mask = doc.clip(wx - 4, b2 - ss, W - wx, ss * 1.32)
    rolling = "".join(anim("W", 1.3 + i * slot, doc.text(SEMI, w, wx, b2, ss, "ink", track=tr)[0]) for i, w in enumerate(words))
    hold = 100 / len(words)
    doc.css.append(f".W{{animation:roll {slot * len(words):.1f}s {EASE} infinite both}}"
                   f"@keyframes roll{{0%{{transform:translateY({roll:.0f}px)}}6%,{hold:.2f}%{{transform:none}}"
                   f"{hold + 6:.2f}%,100%{{transform:translateY(-{roll:.0f}px)}}}}")
    parts.append(anim("u", .9, l1 + l2) + f'<g clip-path="url(#{mask})">{rolling}</g>')

    rule = b2 + 48
    parts.append(anim("fade", 1.1, f'<rect x="{x0}" y="{num(rule)}" width="{W - 2 * x0}" height="1" fill="{t["line"]}"/>'))
    by = rule + 42
    s1, _ = doc.text(REG, "Freelancer and software engineering student at CTU Prague.", x0, by, 15.5, "muted")
    s2, _ = doc.text(MED, "portfolio.princdev.com", W - x0 - 19, by, 15.5, "ink", anchor="end")
    parts.append(anim("u", 1.15, s1 + s2 + f'<g class="nudge">{doc.arrow(W - x0 - 10.5, by - 11, 10.5, t["ink"])}</g>'))
    H = by + 50
    return doc.svg(W, H, doc.card(W, H) + "".join(parts),
                   "Roman Princ. Full-stack engineer in Prague, available for freelance. I build web apps, mobile apps, backends and whole products.")


PILLS = [  # name, label, filled
    ("portfolio", "Portfolio", True),
    ("linkedin", "LinkedIn", False),
    ("email", "Email", False),
    ("wingman", "Wingman", False),
]


def pill(doc, label, filled, delay, m=3, first=7.5):
    """A button: the label and ↗, with a little margin either side so a row of them breathes. The first one's left
    margin lines it up with the cards' edges."""
    t = doc.t
    h, size, pad = 44, 16, 22
    tw = MED.width(label, size)
    w = pad + tw + 10 + 10.5 + pad - 2
    color = "invink" if filled else "ink"
    edge = "" if filled or t["edge"] == "none" else f' stroke="{t["edge"]}"'
    body = (f'<rect x="{first + .5}" y=".5" width="{num(w - 1)}" height="{h - 1}" rx="{(h - 1) / 2}" fill="{t["inv"] if filled else t["card"]}"{edge}/>'
            + doc.text(MED, label, first + pad, 27.9, size, color)[0]
            + anim("nudge", delay, doc.arrow(first + pad + tw + 10, 16.6, 10.5, t[color])))
    return doc.svg(first + w + m, h, body, label)


WINGMAN = ("It keeps searching for your routes and pings your phone when a fare drops or a faster flight appears. "
           "Flexible months, self-transfers and advice on whether to buy or wait. A web app in ten languages, "
           "the iPhone app on its way.")
NOTIFICATIONS = [  # the title's parts (None for the plane, a pair for a colour), the body
    (["PRG", None, "LIS · 116 € ", ("▼7 €", "muted")], "Prague → Lisbon: the same flight got cheaper. Fri 13 Nov, LOT via Warsaw."),
    (["PRG", None, "LIS · 3 h 40 ", ("▼2 h 15", "muted")], "A faster flight: direct, Smartwings QS1176 for 159 €, Fri 13 Nov."),
    (["PRG", None, "BKK · 740 € ", ("New low", "muted")], "The cheapest round trip yet: 14 days in February, via Istanbul."),
]


def notification(doc, x, y, w, title, body, icon, shadow):
    """A macOS notification from Wingman, as the landing page shows them."""
    t = doc.t
    pad, isz = 12, 30
    tx = x + pad + isz + 11
    lines = rows(REG, body, 11.5, x + w - pad - tx)
    h = 52 + 15 * len(lines)
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="15" fill="{t["notif"]}" stroke="{t["notifedge"]}" filter="url(#{shadow})"/>',
           f'<image href="{icon}" x="{x + pad}" y="{y + pad}" width="{isz}" height="{isz}"/>',
           doc.text(MED, "WINGMAN", tx, y + 21, 9.5, "muted", track=.06)[0],
           doc.text(REG, "now", x + w - pad, y + 21, 10.5, "dim", anchor="end")[0]]
    pen = tx
    for part in title:
        if part is None:
            out.append(plane(pen + 10, y + 38 - 13 * CAP / 2, 12, t["ink"]))
            pen += 20
            continue
        s, color = part if isinstance(part, tuple) else (part, "ink")
        markup, pw = doc.text(MED, s, pen, y + 38, 13, color)
        out.append(markup)
        pen += pw
    out += [doc.text(REG, line, tx, y + 55 + 15 * i, 11.5, "ink")[0] for i, line in enumerate(lines)]
    return "".join(out)


def wingman(doc):
    W, H, x0 = 1000, 600, 56
    t = doc.t
    clip = doc.clip(8, 8, W - 16, H - 16, 24)
    parts = []
    label, _ = doc.text(MED, "Now building", x0 + 16, 94, 14.5, "muted")
    parts.append(anim("u", .1, doc.dot(x0 + 4, 94 - 14.5 * CAP / 2, 3.5) + label))
    parts.append(anim("u", .18, doc.text(BOLD, "Wingman", x0 - 3, 176, 78, "ink", track=-.045)[0]))
    parts.append(anim("u", .26, doc.text(SEMI, "Flight price tracker", x0, 218, 27, "muted", track=-.02)[0]))
    desc, n = doc.para(REG, WINGMAN, x0, 266, 16, 352, 25, "muted")
    parts.append(anim("u", .34, desc))

    chips, cx, cy = [], x0, 266 + (n - 1) * 25 + 28
    for name in ["Python", "FastAPI", "PostgreSQL", "React", "SwiftUI", "Web Push"]:
        cw = MED.width(name, 12.5) + 24
        if cx + cw > x0 + 360:
            cx, cy = x0, cy + 35
        chips.append(f'<rect x="{num(cx + .5)}" y="{num(cy + .5)}" width="{num(cw - 1)}" height="27" rx="13.5" fill="none" stroke="{t["line"]}"/>'
                     + doc.text(MED, name, cx + 12, cy + 18.2, 12.5, "muted")[0])
        cx += cw + 6
    parts.append(anim("u", .42, "".join(chips)))

    cta_y, lw = H - 8 - 48 - 46, MED.width("wingmanfares.com", 15.5)
    parts.append(anim("u", .5, f'<rect x="{x0}" y="{cta_y}" width="{num(22 + lw + 10 + 10.5 + 20)}" height="46" rx="23" fill="{t["inv"]}"/>'
                      + doc.text(MED, "wingmanfares.com", x0 + 22, cta_y + 28.6, 15.5, "invink")[0]
                      + anim("nudge", 0, doc.arrow(x0 + 22 + lw + 10, cta_y + 17.6, 10.5, t["invink"]))))

    big, small = doc.shadow(22, 24), doc.shadow(8, 12, .7)
    mac = macbook(doc, 500, 92, 524, 1040 / 658, media("wingman-mac.webp"))
    phone, _ = iphone(doc, 438, 288, 128, media("wingman-phone.webp"))
    icon = media("wingman-icon.svg")
    period = 4.2 * len(NOTIFICATIONS)
    pushes = "".join(anim("nt", 2.2 + i * 4.2, f'<g transform="translate(680 112)">{notification(doc, 0, 0, 298, ti, body, icon, small)}</g>')
                     for i, (ti, body) in enumerate(NOTIFICATIONS))
    doc.css.append(f".nt{{animation:nt {period:.1f}s {EASE} infinite both}}"
                   f"@keyframes nt{{0%{{opacity:0;transform:translateY(-14px)}}4%,28%{{opacity:1;transform:none}}33%,100%{{opacity:0;transform:translateY(-6px)}}}}")
    devices = (anim("u2", .3, f'<g filter="url(#{big})">{mac}</g>') + pushes
               + anim("u2", .55, f'<g class="bob"><g filter="url(#{big})">{phone}</g></g>'))
    parts.append(f'<g clip-path="url(#{clip})">{devices}</g>')
    return doc.svg(W, H, doc.card(W, H) + "".join(parts),
                   "Now building: Wingman, a flight price tracker. Its dashboard on a MacBook, its route globe on an iPhone, and its price alerts.")


# the smaller cards, two to a row


def small_card(doc, number, title, tagline, corner, stack, visual, label):
    W, H = 500, 440
    t = doc.t
    clip = doc.clip(8, 8, W - 16, H - 16, 24)
    parts = [anim("fade", .1, doc.text(MED, number, 40, 46, 13, "dim")[0] + doc.text(MED, corner, W - 40, 46, 13, "muted", anchor="end")[0]),
             f'<g clip-path="url(#{clip})">{visual(doc)}</g>',
             anim("u", .25, doc.text(BOLD, title, 38, 340, 34, "ink", track=-.035)[0]
                  + anim("nudge", .4, doc.arrow(W - 53, 316, 13, t["muted"], 2))),
             anim("u", .33, doc.text(REG, tagline, 40, 369, 15.5, "muted")[0] + doc.text(REG, stack, 40, 403, 13, "dim")[0])]
    return doc.svg(W, H, doc.card(W, H) + "".join(parts), label)


def powderline_visual(doc):
    doc.css.append(".kb{transform-box:fill-box;transform-origin:50% 35%;animation:kb 16s ease-in-out infinite alternate}"
                   "@keyframes kb{to{transform:scale(1.09)}}")
    sh = doc.shadow(14, 16)
    return anim("u2", .2, f'<g filter="url(#{sh})">{macbook(doc, 93.5, 70, 300, 1.6, media("powderline-mac.webp"), "kb")}</g>')


def chester_visual(doc):
    sh = doc.shadow(12, 14)
    out = []
    for i, (name, x, y, w, turn) in enumerate([("chester-device.webp", 130, 94, 84, -8), ("chester-export.webp", 286, 94, 84, 8),
                                                ("chester-data.webp", 203, 70, 94, 0)]):
        phone, h = iphone(doc, x, y, w, media(name))
        out.append(anim("u2", .15 + i * .12, f'<g class="bob" style="animation-delay:{-i * 1.7:.1f}s">'
                        f'<g transform="rotate({turn} {num(x + w / 2)} {num(y + h / 2)})" filter="url(#{sh})">{phone}</g></g>'))
    return "".join(out)


TERMINAL = [  # the image editor's own commands, from its README
    ("python main.py --rotate 90 input.jpg output.jpg", "output.jpg"),
    ("python main.py --bw --lighten 25 input.jpg output.jpg", "output.jpg"),
    ("python main.py --sharpen --darken 10 input.jpg output.jpg", "output.jpg"),
    ("python main.py --ed input.jpg edges.jpg", "edges.jpg"),
]


def terminal_visual(doc):
    """The commands typed one after another, each printing its line, then the screen clears and it starts over."""
    t = doc.t
    frame, inside, top = window(doc, 34, 64, 432, 222, "editor — zsh")
    size, lead = 10.5, 15
    cw = MONO.width("0", size)
    x0, period, end = 34 + 14, 13.0, 96.0
    pct = lambda s: s / period * 100
    starts, s = [], .8
    for cmd, _ in TERMINAL:
        starts.append(s)
        s += len(cmd) * .032 + .6
    out = []
    for i, (cmd, saved) in enumerate(TERMINAL):
        y = top + 22 + i * 37
        st, typed = pct(starts[i]), pct(starts[i] + len(cmd) * .032)
        shown, cursor_end = pct(starts[i] + len(cmd) * .032 + .25), pct(starts[i + 1]) if i + 1 < len(TERMINAL) else end
        n = len(cmd)
        doc.css.append(
            f".k{i}{{animation:k{i} {period}s linear infinite}}"
            f"@keyframes k{i}{{0%,{st:.2f}%{{transform:none;animation-timing-function:steps({n},end)}}"
            f"{typed:.2f}%,{end}%{{transform:translateX({n * cw:.2f}px)}}{end + .01}%,100%{{transform:none}}}}"
            f".p{i}{{animation:p{i} {period}s linear infinite}}@keyframes p{i}{{0%,{st:.2f}%{{opacity:0}}{st + .01:.2f}%,{end}%{{opacity:1}}{end + .01}%,100%{{opacity:0}}}}"
            f".o{i}{{animation:o{i} {period}s linear infinite}}@keyframes o{i}{{0%,{shown:.2f}%{{opacity:0}}{shown + .01:.2f}%,{end}%{{opacity:1}}{end + .01}%,100%{{opacity:0}}}}"
            f".q{i}{{animation:q{i} {period}s linear infinite}}@keyframes q{i}{{0%,{st:.2f}%{{opacity:0}}{st + .01:.2f}%,{cursor_end:.2f}%{{opacity:1}}{cursor_end + .01:.2f}%,100%{{opacity:0}}}}")
        tx = x0 + 2 * cw
        out.append(f'<g class="p{i}">{doc.text(MONO, "%", x0, y, size, "dim")[0]}</g>'
                   + doc.text(MONO, cmd, tx, y, size, "ink")[0]
                   + f'<g class="cv k{i}"><rect x="{num(tx)}" y="{num(y - 11)}" width="{num((n + 2) * cw)}" height="{lead}" fill="{t["win"]}"/>'
                   f'<rect class="q{i}" x="{num(tx)}" y="{num(y - 9.5)}" width="{num(cw)}" height="12.5" fill="{t["ink"]}"/></g>'
                   + f'<g class="o{i}">{doc.text(MONO, "Image saved successfully to " + saved, x0, y + lead, size, "muted")[0]}</g>')
    return anim("u2", .2, frame + f'<g clip-path="url(#{inside})">{"".join(out)}</g>')


def spreadsheet_visual(doc):
    """A sheet (an illustration): a cost changes every 1.4 seconds and the totals under it recalculate."""
    t = doc.t
    frame, inside, top = window(doc, 34, 64, 432, 222, "budget.xlsx")
    items = ["Payroll", "Hosting", "Licences", "Travel", "Marketing", "Other"]
    cols = [(34, 22), (56, 150), (206, 112), (318, 112), (430, 36)]  # x, width: the row numbers, A, B, C, D
    bar, head, row = 20, 16, 18.5
    gy = top + bar
    lines = [f'<rect x="34" y="{top + bar - .5}" width="432" height=".5" fill="{t["line"]}"/>']
    for x, w in cols[1:]:
        lines.append(f'<rect x="{x}" y="{gy}" width=".5" height="{num(head + 8 * row)}" fill="{t["line"]}"/>')
    for r in range(9):
        lines.append(f'<rect x="34" y="{num(gy + head + r * row)}" width="432" height=".5" fill="{t["line"]}"/>')
    labels = []
    for (x, w), letter in zip(cols[1:], "ABCD"):
        labels.append(doc.text(MED, letter, x + w / 2, gy + 11.5, 9.5, "dim", anchor="middle")[0])
    cell = lambda r: gy + head + r * row + 12.8  # the baseline of row r (0 is the sheet's row 1)
    for r in range(8):
        labels.append(doc.text(MED, str(r + 1), 45, cell(r), 9.5, "dim", anchor="middle")[0])
    labels.append(doc.text(MED, "Item", 64, cell(0), 10.5, "muted")[0])
    labels += [doc.text(MED, h, cols[c][0] + cols[c][1] - 8, cell(0), 10.5, "muted", anchor="end")[0] for c, h in [(2, "Net"), (3, "Gross")]]
    labels += [doc.text(REG, name, 64, cell(i + 1), 10.5, "ink")[0] for i, name in enumerate(items)]
    labels.append(doc.text(MED, "Total", 64, cell(7), 10.5, "ink")[0])
    labels.append(doc.text(MONO, "B8 =SUM(B2:B7)", 456, top + 13.5, 9.5, "dim", anchor="end")[0])

    rnd, values, hot, frames = random.Random(7), [1840, 620, 940, 120, 260, 310], 0, []
    for _ in range(6):
        hot = rnd.choice([j for j in range(6) if j != hot])
        values = values[:]
        values[hot] = max(40, round(values[hot] * rnd.uniform(.72, 1.32) / 5) * 5)
        frames.append((hot, values))
    step = 1.4
    period = step * len(frames)
    doc.css.append(f".fr{{animation:fr {period:.1f}s steps(1,end) infinite}}@keyframes fr{{0%{{opacity:1}}{100 / len(frames):.3f}%,100%{{opacity:0}}}}")
    shown = []
    money = lambda v: f"{v:,}"
    for k, (hot, values) in enumerate(frames):
        f = [f'<rect x="{cols[2][0] + 1}" y="{num(gy + head + (hot + 1) * row + 1)}" width="{cols[2][1] - 1.5}" height="{row - 1.5}" fill="{t["ink"]}"/>',
             doc.text(MONO, f"B{hot + 2}", 46, top + 13.5, 9.5, "muted")[0],
             doc.text(MONO, "fx", 76, top + 13.5, 9.5, "dim")[0],
             doc.text(MONO, f"={values[hot]}", 96, top + 13.5, 9.5, "ink")[0]]
        for i, v in enumerate(values):
            f.append(doc.text(MED, money(v), cols[2][0] + cols[2][1] - 8, cell(i + 1), 10.5, "invink" if i == hot else "ink", anchor="end", features=TNUM)[0])
            f.append(doc.text(MED, money(round(v * 1.21)), cols[3][0] + cols[3][1] - 8, cell(i + 1), 10.5, "muted", anchor="end", features=TNUM)[0])
        total = sum(values)
        f.append(doc.text(SEMI, money(total), cols[2][0] + cols[2][1] - 8, cell(7), 10.5, "ink", anchor="end", features=TNUM)[0])
        f.append(doc.text(SEMI, money(round(total * 1.21)), cols[3][0] + cols[3][1] - 8, cell(7), 10.5, "ink", anchor="end", features=TNUM)[0])
        shown.append(anim("fr", k * step - period, "".join(f)))
    return anim("u2", .2, frame + f'<g clip-path="url(#{inside})">{"".join(lines + labels + shown)}</g>')


CARDS = [  # name, number, title, tagline, corner, stack, visual, link, label
    ("powderline", "02", "Powderline", "Snowboarding in the browser", "2026", "Three.js · React · Supabase · WebRTC", powderline_visual,
     "https://portfolio.princdev.com/work/powderline", "Powderline, a snowboarding game in the browser: its procedural mountain on a MacBook."),
    ("chester", "03", "CHESTER", "IoT gateways, from a phone", "2022–2023", "React Native · REST API · 5th place at SOČ", chester_visual,
     "https://portfolio.princdev.com/work/chester-iot", "CHESTER, a React Native app for IoT gateways: three of its screens on iPhones."),
    ("image-editor", "04", "Image editor", "Filters through the Fourier transform", "2024", "Python · NumPy · SciPy", terminal_visual,
     "https://portfolio.princdev.com/work/image-editor", "An image editor with a command line: its commands typed in a terminal."),
    ("excel-engine", "05", "Excel engine", "A spreadsheet engine, from scratch", "", "C++ · performance", spreadsheet_visual,
     "https://portfolio.princdev.com/work/excel-engine", "An Excel engine in C++: a sheet recalculating its totals (an illustration)."),
]


TOOLS = [
    [("TypeScript", "typescript"), ("React", "react"), ("Next.js", "nextdotjs"), ("Angular", "angular"), ("Node.js", "nodedotjs"),
     ("GraphQL", "graphql"), ("Tailwind CSS", "tailwindcss"), ("Three.js", "threedotjs"), ("Electron", "electron"),
     ("Ionic", "ionic"), ("Capacitor", "capacitor"), ("Vite", "vite")],
    [("Python", "python"), ("FastAPI", "fastapi"), ("PostgreSQL", "postgresql"), ("Swift", "swift"), ("C#", None),
     (".NET", "dotnet"), ("C++", "cplusplus"), ("Docker", "docker"), ("Jenkins", "jenkins"), ("Git", "git"),
     ("Redis", "redis"), ("Supabase", "supabase"), ("Prisma", "prisma"), ("Ruby on Rails", "rubyonrails")],
]


def icon_path(slug):
    with open(os.path.join(HERE, "media", "icons", f"{slug}.svg")) as f:
        return re.search(r' d="([^"]+)"', f.read()).group(1)


def toolbox(doc):
    """Two rows of tools drifting past each other, fading out at the card's edges."""
    W, H = 1000, 304
    t = doc.t
    clip = doc.clip(8, 8, W - 16, H - 16, 24)
    parts = [anim("u", .1, doc.text(BOLD, "Toolbox", 46, 84, 36, "ink", track=-.04)[0]),
             anim("u", .2, doc.text(REG, "What I reach for, from the screen to the server.", 48, 114, 15.5, "muted")[0])]
    fade, mask = doc.id("g"), doc.id("m")
    doc.defs.append(f'<linearGradient id="{fade}" x1="8" x2="{W - 8}" y1="0" y2="0" gradientUnits="userSpaceOnUse">'
                    f'<stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".12" stop-color="#fff"/>'
                    f'<stop offset=".88" stop-color="#fff"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>'
                    f'<mask id="{mask}" maskUnits="userSpaceOnUse" x="0" y="0" width="{W}" height="{H}">'
                    f'<rect x="8" y="136" width="{W - 16}" height="{H - 144}" fill="url(#{fade})"/></mask>')
    drift = []
    for r, tools in enumerate(TOOLS):
        y, x, items = 146 + r * 64, 0.0, []
        for name, slug in tools:
            tw = MED.width(name, 15)
            w = (46 if slug else 20) + tw + 20
            items.append(f'<rect x="{num(x)}" y="{y}" width="{num(w)}" height="48" rx="24" fill="{t["soft"]}"/>')
            if slug:
                items.append(f'<path transform="translate({num(x + 17)} {y + 14}) scale({20 / 24:.4f})" d="{icon_path(slug)}" fill="{t["ink"]}"/>')
            items.append(doc.text(MED, name, x + (46 if slug else 20), y + 29.4, 15, "ink")[0])
            x += w + 10
        rid = doc.id("row")
        doc.defs.append(f'<g id="{rid}">{"".join(items)}</g>')
        secs = x / 26
        frames = f"to{{transform:translateX(-{x:.1f}px)}}" if r == 0 else f"from{{transform:translateX(-{x:.1f}px)}}to{{transform:none}}"
        doc.css.append(f".m{r}{{animation:m{r} {secs:.1f}s linear infinite}}@keyframes m{r}{{{frames}}}")
        drift.append(anim("u", .3 + r * .1, f'<g class="m{r}"><use href="#{rid}" x="8"/><use href="#{rid}" x="{num(x + 8)}"/></g>'))
    parts.append(f'<g clip-path="url(#{clip})"><g mask="url(#{mask})">{"".join(drift)}</g></g>')
    return doc.svg(W, H, doc.card(W, H) + "".join(parts),
                   "Toolbox: TypeScript, React, Next.js, Angular, Node.js, GraphQL, Python, FastAPI, PostgreSQL, Swift, C#, .NET, C++, Docker and more.")


# --------------------------------------------------------------------------------------------------- activity


def calendar():
    """The public contribution calendar: each day's count and level (0 to 4), and the year's total."""
    req = urllib.request.Request(f"https://github.com/users/{USER}/contributions", headers={"User-Agent": "Mozilla/5.0 (profile build)"})
    page = urllib.request.urlopen(req, timeout=30).read().decode()
    tips = dict(re.findall(r'<tool-tip[^>]*\sfor="([^"]+)"[^>]*>([^<]*)</tool-tip>', page))
    days = {}
    for attrs in re.findall(r"<td([^>]*ContributionCalendar-day[^>]*)>", page):
        date, level, cid = (re.search(p, attrs) for p in (r'data-date="([\d-]+)"', r'data-level="(\d)"', r'\sid="([^"]+)"'))
        if date and level and cid:
            count = re.match(r"([\d,]+) contribution", tips.get(cid.group(1), ""))
            days[dt.date.fromisoformat(date.group(1))] = (int(count.group(1).replace(",", "")) if count else 0, int(level.group(1)))
    if len(days) < 300:
        raise SystemExit(f"the calendar didn't parse ({len(days)} days)")
    total = re.search(r"([\d,]+)\s+contributions?\s+in the last year", page)
    return days, int(total.group(1).replace(",", "")) if total else sum(c for c, _ in days.values())


def streaks(days):
    dates = sorted(days)
    longest = run = 0
    for d in dates:
        run = run + 1 if days[d][0] else 0
        longest = max(longest, run)
    i = len(dates) - 1
    if not days[dates[i]][0]:
        i -= 1  # today isn't over yet
    current = 0
    while i >= 0 and days[dates[i]][0]:
        current, i = current + 1, i - 1
    return longest, current, max(dates, key=lambda d: days[d][0])


def bezier(p, steps=400):
    """The length of a cubic Bézier, by walking along it."""
    pts = [tuple((1 - s) ** 3 * p[0][k] + 3 * (1 - s) ** 2 * s * p[1][k] + 3 * (1 - s) * s * s * p[2][k] + s ** 3 * p[3][k] for k in (0, 1))
           for s in (i / steps for i in range(steps + 1))]
    return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))


def activity(doc, days, total):
    """The last twelve months: the total, the streaks, the calendar popping in, then a plane flying over it."""
    W, x0 = 1000, 48
    t = doc.t
    clip = doc.clip(8, 8, W - 16, 1000, 24)
    longest, current, best = streaks(days)
    plural = lambda n, word: f"{n} {word}{'' if n == 1 else 's'}"

    parts = [anim("u", .1, doc.text(MED, "Activity", x0, 62, 14.5, "muted")[0])]
    big, bw = doc.text(BOLD, f"{total:,}", x0 - 2, 126, 60, "ink", track=-.04, features=TNUM)
    parts.append(anim("u", .15, big + doc.text(SEMI, "contributions in the last year", x0 + bw + 12, 126, 22, "muted", track=-.01)[0]))
    stats = [("Longest streak", plural(longest, "day")), ("Current streak", plural(current, "day")),
             (f"Best day, {best.day} {best:%b}", plural(days[best][0], "contribution"))]
    xe = W - x0
    for i, (label, value) in enumerate(reversed(stats)):
        v, vw = doc.text(BOLD, value, xe, 100, 22, "ink", track=-.02, anchor="end")
        lab, lw = doc.text(REG, label, xe, 123, 13, "muted", anchor="end")
        parts.append(anim("u", .25 + (2 - i) * .07, v + lab))
        xe -= max(vw, lw) + 44

    dates = sorted(days)
    first = dates[0] - dt.timedelta(days=(dates[0].weekday() + 1) % 7)  # the Sunday the first column starts on
    cols = (dates[-1] - first).days // 7 + 1
    gap = 3
    size = (W - 2 * x0 - (cols - 1) * gap) / cols
    gy = 178
    cells, labels, last_label = [], [], -9
    for d in dates:
        c, r = (d - first).days // 7, (d - first).days % 7
        count, level = days[d]
        cells.append(f'<rect class="c d{c + r}" x="{num(x0 + c * (size + gap))}" y="{num(gy + r * (size + gap))}" width="{num(size)}" '
                     f'height="{num(size)}" rx="2.6" fill="{t["ink"]}" fill-opacity="{t["cells"][level]}"/>')
    for c in range(cols):
        week = first + dt.timedelta(days=7 * c)
        if any((week + dt.timedelta(days=k)).day == 1 for k in range(7)) and c - last_label > 3 and c < cols - 2:
            month = next(week + dt.timedelta(days=k) for k in range(7) if (week + dt.timedelta(days=k)).day == 1)
            labels.append(doc.text(REG, f"{month:%b}", x0 + c * (size + gap), gy - 10, 11, "dim")[0])
            last_label = c
    doc.css.append(f".c{{transform-box:fill-box;transform-origin:center;animation:pop .9s {EASE} both}}"
                   "@keyframes pop{from{opacity:0;transform:scale(.2)}}"
                   + "".join(f".d{k}{{animation-delay:{.35 + k * .016:.3f}s}}" for k in range(cols + 7)))
    parts.append(anim("fade", .3, "".join(labels)) + "".join(cells))

    foot = gy + 7 * (size + gap) - gap + 34
    updated = dt.date.today()
    parts.append(anim("fade", .9, doc.text(REG, f"Updated {updated.day} {updated:%B %Y}", x0, foot, 12, "dim")[0]))
    legend, lx = [], W - x0
    more, mw = doc.text(REG, "More", lx, foot, 12, "dim", anchor="end")
    lx -= mw + 8
    for level in reversed(range(5)):
        lx -= 11
        legend.append(f'<rect x="{num(lx)}" y="{num(foot - 9.5)}" width="11" height="11" rx="2.4" fill="{t["ink"]}" fill-opacity="{t["cells"][level]}"/>')
        lx -= 3
    less, _ = doc.text(REG, "Less", lx - 5, foot, 12, "dim", anchor="end")
    parts.append(anim("fade", .9, more + "".join(legend) + less))
    H = foot + 32

    # the plane: across the calendar every quarter of a minute, a dotted contrail drawing itself behind it
    p = [(-40, gy + 96), (260, gy - 34), (640, gy + 156), (W + 40, gy + 24)]
    d = f"M{p[0][0]} {p[0][1]}C{p[1][0]} {p[1][1]} {p[2][0]} {p[2][1]} {p[3][0]} {p[3][1]}"
    length, trail = bezier(p), doc.id("m")
    fly = "dur=\"4.6s\" calcMode=\"spline\" keySplines=\".45 0 .25 1\""
    doc.defs.append(f'<mask id="{trail}" maskUnits="userSpaceOnUse" x="0" y="0" width="{W}" height="{num(H)}">'
                    f'<path d="{d}" fill="none" stroke="#fff" stroke-width="12" stroke-dasharray="{length:.0f} {length:.0f}" stroke-dashoffset="{length:.0f}">'
                    f'<animate id="fly" attributeName="stroke-dashoffset" values="{length:.0f};0" keyTimes="0;1" {fly} begin="2.4s;fly.end+11s" fill="freeze"/>'
                    f'</path></mask>')
    parts.append(f'<g class="plane" clip-path="url(#{clip})">'
                 f'<g mask="url(#{trail})" opacity="0"><animate attributeName="opacity" values="1;1;0" keyTimes="0;.62;1" dur="8s" begin="fly.begin"/>'
                 f'<path d="{d}" fill="none" stroke="{t["ink"]}" stroke-opacity=".5" stroke-width="1.6" stroke-linecap="round" stroke-dasharray="0 7"/></g>'
                 f'<g opacity="0"><set attributeName="opacity" to="1" dur="4.6s" begin="fly.begin"/>'
                 f'<animateMotion path="{d}" rotate="auto" keyPoints="0;1" keyTimes="0;1" {fly} begin="fly.begin"/>'
                 f'{plane(0, 0, 20, t["ink"])}</g></g>')
    return doc.svg(W, H, doc.card(W, H) + "".join(parts),
                   f"{total:,} contributions on GitHub in the last year. Longest streak {plural(longest, 'day')}, current streak {plural(current, 'day')}.")


def footer(doc):
    W, x0 = 1000, 56
    t = doc.t
    parts = [anim("u", .1, doc.text(MED, "Have a project in mind?", x0, 70, 14.5, "muted")[0])]
    line, track = "Let’s build something.", -.045
    size = min(92, (W - 2 * x0) / BOLD.width(line, 1, track))
    base = 104 + size * CAP
    parts.append(letters(doc, line, x0 - size * .03, base, size, track, .15, 3.0)[0])
    mail, mw = doc.text(SEMI, "roman.princ00@gmail.com", x0, base + 56, 28, "muted", track=-.015)
    parts.append(anim("u", .8, mail + anim("nudge", .2, doc.arrow(x0 + mw + 12, base + 56 - 19, 16, t["muted"], 2.2))))
    rule = base + 96
    parts.append(anim("fade", 1, f'<rect x="{x0}" y="{num(rule)}" width="{W - 2 * x0}" height="1" fill="{t["line"]}"/>'))
    by = rule + 40
    parts.append(anim("fade", 1.05, doc.text(REG, f"© {dt.date.today().year} Roman Princ", x0, by, 14, "dim")[0]
                      + doc.text(REG, "Made with care in Prague", W - x0, by, 14, "dim", anchor="end")[0]))
    H = by + 44
    return doc.svg(W, H, doc.card(W, H) + "".join(parts), "Let's build something. Email roman.princ00@gmail.com.")


# ------------------------------------------------------------------------------------------------------- build


LINKS = {
    "portfolio": "https://portfolio.princdev.com",
    "linkedin": "https://www.linkedin.com/in/roman-princ-717a58244/",
    "email": "mailto:roman.princ00@gmail.com",
    "wingman": "https://wingmanfares.com",
}


def picture(name, alt, link, size='width="100%"'):
    """A picture in the theme GitHub shows, as a link."""
    return (f'<a href="{link}"><picture><source media="(prefers-color-scheme: dark)" srcset="assets/{name}-dark.svg">'
            f'<img alt="{html.escape(alt)}" src="assets/{name}-light.svg" {size}></picture></a>')


def readme(alts):
    """The README: every picture in one block, so the gaps between them come from their own margins."""
    pills = " ".join(picture(f"pill-{name}", label, LINKS[name], 'height="40"') for name, label, _ in PILLS)
    cards = "".join(picture(name, alts[name], link, 'width="50%"') for name, *_, link, _ in CARDS)
    body = "".join([
        picture("hero", alts["hero"], LINKS["portfolio"]), "<br>", pills, "<br>",
        picture("wingman", alts["wingman"], LINKS["wingman"]), cards,
        picture("toolbox", alts["toolbox"], LINKS["portfolio"] + "/#about"),
        picture("activity", alts["activity"], f"https://github.com/{USER}?tab=repositories"),
        picture("footer", alts["footer"], LINKS["email"]),
    ])
    return ("<!-- Drawn by scripts/build.py and redrawn every day by .github/workflows/build.yml: change the script, "
            f"not this file. -->\n\n<div>{body}</div>\n")


def write(name, svg):
    path = os.path.join(OUT, name)
    with open(path, "w") as f:
        f.write(svg)
    return f"{name} {len(svg) // 1024} KB"


def main():
    os.makedirs(OUT, exist_ok=True)
    days, total = calendar()
    done, alts = [], {}

    def draw(name, theme, fn, *args):
        doc = Doc(theme)
        done.append(write(f"{name}-{theme}.svg", fn(doc, *args)))
        alts[name] = doc.label

    for theme in THEMES:
        draw("hero", theme, hero)
        for i, (name, label, filled) in enumerate(PILLS):
            draw(f"pill-{name}", theme, pill, label, filled, i * .25, 3, 7.5 if i == 0 else 3)
        draw("wingman", theme, wingman)
        for name, number, title, tagline, corner, stack, visual, _, label in CARDS:
            draw(name, theme, small_card, number, title, tagline, corner, stack, visual, label)
        draw("toolbox", theme, toolbox)
        draw("activity", theme, activity, days, total)
        draw("footer", theme, footer)
    with open(os.path.join(ROOT, "README.md"), "w") as f:
        f.write(readme(alts))
    print("\n".join(done))


if __name__ == "__main__":
    main()
