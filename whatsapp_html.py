#!/usr/bin/env python3
"""
Converte uma exportação de conversa do WhatsApp (.txt) em um HTML navegável.

O HTML gerado permite buscar mensagens, filtrar por intervalo de datas,
alterar a ordem cronológica e visualizar anexos disponíveis na mesma pasta.

Uso:
    python whatsapp_html.py conversa.txt
    python whatsapp_html.py conversa.txt -o conversa.html
    python whatsapp_html.py conversa.txt --me "Fabio" --title "Conversa"
    python whatsapp_html.py conversa.txt --date-order dmy
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote


# Formato comum no Android:
# 30/07/2026 22:15 - Fabio: Mensagem
# 30/07/2026, 22:15 - Fabio: Mensagem
ANDROID_RE = re.compile(
    r"^(?P<date>\d{1,2}/\d{1,2}/\d{2,4}),?\s+"
    r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?)\s+-\s+"
    r"(?P<body>.*)$"
)

# Formato comum no iPhone:
# [30/07/2026, 22:15:10] Fabio: Mensagem
IOS_RE = re.compile(
    r"^\[(?P<date>\d{1,2}/\d{1,2}/\d{2,4}),?\s+"
    r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?)\]\s+"
    r"(?P<body>.*)$"
)

# re.S permite que o conteúdo da mensagem continue em outras linhas. Sem isso,
# qualquer legenda ou texto abaixo de um anexo era classificado como mensagem
# do sistema, impedindo a criação da imagem, vídeo, áudio ou link.
SENDER_RE = re.compile(r"^(?P<sender>[^:]{1,100}):\s(?P<text>.*)$", re.S)


@dataclass
class Message:
    timestamp: str
    display_date: str
    sender: Optional[str]
    text: str
    is_system: bool
    index: int
    attachment_name: Optional[str] = None
    attachment_url: Optional[str] = None
    attachment_type: Optional[str] = None


ATTACHMENT_RE = re.compile(
    r"(?P<name>[^\n<>]+?\.(?:jpg|jpeg|png|gif|webp|mp4|mov|avi|mkv|mp3|m4a|aac|ogg|opus|wav|pdf|doc|docx|xls|xlsx|ppt|pptx|txt|zip|rar))(?=\s*(?:\((?:arquivo|ficheiro) anexado\)|$|>))",
    re.I,
)


INVISIBLE_CHARS_RE = re.compile(
    r"[\u200b\u200c\u200d\u200e\u200f\u202a-\u202e\u2060\u2066-\u2069\ufeff]"
)

def clean_filename(value: str) -> str:
    """Normaliza nomes vindos do TXT do WhatsApp."""
    value = INVISIBLE_CHARS_RE.sub("", value)
    value = unicodedata.normalize("NFC", value)
    return value.strip().strip('"').strip("'")

def attachment_kind(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in {".jpg", ".jpeg", ".png", ".gif", ".webp"}: return "image"
    if ext in {".mp4", ".mov", ".avi", ".mkv"}: return "video"
    if ext in {".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav"}: return "audio"
    return "file"

def build_attachment_index(media_dir: Optional[Path]) -> dict[str, Path]:
    """Indexa anexos na pasta informada e em seus subdiretórios."""
    if not media_dir or not media_dir.exists() or not media_dir.is_dir():
        return {}

    result: dict[str, Path] = {}
    for f in media_dir.rglob("*"):
        if f.is_file():
            key = clean_filename(f.name).casefold()
            result.setdefault(key, f.resolve())
    return result


def attachment_url_for(found: Path, output_dir: Path) -> str:
    """Cria uma URL válida do HTML até o anexo localizado."""
    found = found.resolve()
    output_dir = output_dir.resolve()

    try:
        relative = os.path.relpath(found, start=output_dir)
        # quote preserva as barras e protege espaços, #, ?, acentos etc.
        return quote(Path(relative).as_posix(), safe="/:")
    except ValueError:
        # No Windows, caminhos em unidades diferentes não podem ser relativos.
        return found.as_uri()


def find_attachment_path(
    attachment_name: str,
    attachment_index: dict[str, Path],
) -> Optional[Path]:
    key = clean_filename(attachment_name).casefold()

    # Correspondência exata após remover caracteres invisíveis.
    found = attachment_index.get(key)
    if found:
        return found

    # Contingência: alguns exports trazem prefixos invisíveis/estranhos.
    # Se houver exatamente um arquivo cujo nome termine com o nome procurado,
    # usamos esse arquivo.
    matches = [
        path
        for indexed_name, path in attachment_index.items()
        if indexed_name.endswith(key) or key.endswith(indexed_name)
    ]
    if len(matches) == 1:
        return matches[0]

    return None


def parse_datetime(date_text: str, time_text: str, date_order: str) -> datetime:
    day_or_month_1, day_or_month_2, year = date_text.split("/")
    year_i = int(year)
    if year_i < 100:
        year_i += 2000

    first = int(day_or_month_1)
    second = int(day_or_month_2)

    if date_order == "dmy":
        day, month = first, second
    else:
        month, day = first, second

    time_parts = [int(part) for part in time_text.split(":")]
    hour, minute = time_parts[0], time_parts[1]
    second_value = time_parts[2] if len(time_parts) == 3 else 0

    return datetime(year_i, month, day, hour, minute, second_value)


def detect_message_start(line: str):
    for regex in (IOS_RE, ANDROID_RE):
        match = regex.match(line)
        if match:
            return match
    return None


def parse_export(
    path: Path,
    date_order: str = "dmy",
    media_dir: Optional[Path] = None,
    output_dir: Optional[Path] = None,
) -> list[Message]:
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    lines = raw.splitlines()

    # Por padrão, os anexos são procurados SOMENTE na mesma pasta do TXT.
    effective_media_dir = media_dir if media_dir is not None else path.resolve().parent
    attachment_index = build_attachment_index(effective_media_dir)
    effective_output_dir = output_dir if output_dir is not None else path.resolve().parent

    messages: list[Message] = []
    current: dict | None = None

    def flush_current() -> None:
        nonlocal current
        if current is None:
            return

        body = current["body"]
        sender_match = SENDER_RE.match(body)

        if sender_match:
            sender = sender_match.group("sender").strip()
            text = sender_match.group("text")
            is_system = False
        else:
            sender = None
            text = body
            is_system = True

        dt = current["datetime"]
        attachment_name = None
        attachment_url = None
        attachment_type = None
        # Em exports sem aquela mídia, o WhatsApp escreve <Mídia oculta> e pode
        # deixar uma legenda terminada em .pdf/.jpg. Essa legenda não é o nome
        # físico do arquivo e não deve ser tratada como uma referência segura.
        hidden_media = "<mídia oculta>" in text.casefold()
        am = None if hidden_media else ATTACHMENT_RE.search(text)
        if am:
            attachment_name = clean_filename(am.group("name"))
            found = find_attachment_path(attachment_name, attachment_index)
            if found:
                attachment_url = attachment_url_for(found, effective_output_dir)
                attachment_type = attachment_kind(attachment_name)
        messages.append(
            Message(
                timestamp=dt.isoformat(),
                display_date=dt.strftime("%d/%m/%Y %H:%M"),
                sender=sender,
                text=text,
                is_system=is_system,
                index=len(messages),
                attachment_name=attachment_name,
                attachment_url=attachment_url,
                attachment_type=attachment_type,
            )
        )
        current = None

    for line in lines:
        match = detect_message_start(line)

        if match:
            flush_current()
            try:
                dt = parse_datetime(
                    match.group("date"),
                    match.group("time"),
                    date_order,
                )
            except ValueError:
                # Caso a linha se pareça com uma mensagem, mas tenha data inválida,
                # ela é anexada à mensagem anterior.
                if messages:
                    messages[-1].text += "\n" + line
                continue

            current = {
                "datetime": dt,
                "body": match.group("body"),
            }
        elif current is not None:
            current["body"] += "\n" + line
        elif line.strip():
            # Texto anterior à primeira mensagem reconhecida.
            messages.append(
                Message(
                    timestamp="",
                    display_date="",
                    sender=None,
                    text=line,
                    is_system=True,
                    index=len(messages),
                )
            )

    flush_current()
    return messages


def build_html(
    messages: list[Message],
    title: str,
    me: str | None = None,
) -> str:
    data_json = json.dumps(
        [asdict(message) for message in messages],
        ensure_ascii=False,
    ).replace("</", "<\\/")

    safe_title = html.escape(title)

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe_title}</title>
<style>
    :root {{
        --header: #075e54;
        --header-dark: #064c44;
        --bg: #efeae2;
        --incoming: #ffffff;
        --outgoing: #d9fdd3;
        --system: #fff3c4;
        --text: #111b21;
        --muted: #667781;
        --border: rgba(17, 27, 33, 0.12);
    }}

    * {{ box-sizing: border-box; }}

    html, body {{
        margin: 0;
        min-height: 100%;
        font-family: Arial, Helvetica, sans-serif;
        color: var(--text);
        background: var(--bg);
    }}

    body {{
        background-image:
            linear-gradient(rgba(239,234,226,.92), rgba(239,234,226,.92)),
            radial-gradient(circle at 20px 20px, rgba(0,0,0,.04) 1px, transparent 1px);
        background-size: auto, 40px 40px;
    }}

    header {{
        position: sticky;
        top: 0;
        z-index: 20;
        background: var(--header);
        color: white;
        padding: 12px 16px;
        box-shadow: 0 2px 8px rgba(0,0,0,.18);
    }}

    .topbar {{
        max-width: 980px;
        margin: auto;
        display: flex;
        gap: 12px;
        align-items: center;
        justify-content: space-between;
        flex-wrap: wrap;
    }}

    .title-area h1 {{
        margin: 0;
        font-size: 18px;
    }}

    .title-area small {{
        opacity: .85;
    }}

    .controls {{
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
    }}

    button, input {{
        border: 0;
        border-radius: 8px;
        font: inherit;
    }}

    button {{
        padding: 9px 12px;
        cursor: pointer;
        background: white;
        color: var(--header-dark);
        font-weight: 700;
    }}

    button:hover {{
        filter: brightness(.96);
    }}

    input, select {{
        padding: 9px 11px;
        outline: none;
    }}

    input[type="search"] {{
        min-width: 220px;
    }}

    input[type="date"] {{
        min-width: 138px;
        padding: 7px 9px;
        background: white;
        color: var(--text);
    }}

    .date-filter {{
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 4px 7px;
        border-radius: 8px;
        background: rgba(255,255,255,.14);
        font-size: 12px;
        white-space: nowrap;
    }}

    #clearDatesButton:disabled {{
        cursor: default;
        opacity: .55;
    }}

    .option-group {{
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 4px 7px;
        border-radius: 8px;
        background: rgba(255,255,255,.14);
        font-size: 12px;
    }}

    .option-group select {{
        max-width: 180px;
        padding: 6px 8px;
    }}

    .option-group input[type="color"] {{
        width: 34px;
        height: 30px;
        padding: 2px;
        min-width: 0;
        cursor: pointer;
        background: white;
    }}

    main {{
        max-width: 980px;
        margin: auto;
        padding: 20px 12px 80px;
    }}

    .day-separator {{
        width: fit-content;
        margin: 18px auto 12px;
        padding: 6px 12px;
        background: #ffffffd9;
        border-radius: 8px;
        box-shadow: 0 1px 2px rgba(0,0,0,.12);
        color: var(--muted);
        font-size: 12px;
        position: sticky;
        top: 84px;
        z-index: 5;
    }}

    .message-row {{
        display: flex;
        margin: 3px 0;
    }}

    .message-row.outgoing {{
        justify-content: flex-end;
    }}

    .message-row.incoming {{
        justify-content: flex-start;
    }}

    .bubble {{
        max-width: min(76%, 720px);
        padding: 7px 9px 5px;
        border-radius: 8px;
        box-shadow: 0 1px 1px rgba(0,0,0,.12);
        white-space: pre-wrap;
        overflow-wrap: anywhere;
        line-height: 1.35;
    }}

    .incoming .bubble {{
        background: var(--incoming);
        border-top-left-radius: 2px;
    }}

    .outgoing .bubble {{
        background: var(--outgoing);
        border-top-right-radius: 2px;
    }}

    .sender {{
        font-size: 12px;
        font-weight: 700;
        margin-bottom: 3px;
    }}


    .attachment {{ margin-top: 7px; }}
    .attachment img, .attachment video {{ display:block; max-width:100%; max-height:420px; border-radius:8px; }}
    .attachment audio {{ width:min(100%,420px); }}
    .attachment-link {{ display:inline-block; margin-top:6px; padding:7px 9px; border-radius:7px; background:rgba(0,0,0,.06); color:inherit; text-decoration:none; font-weight:700; word-break:break-all; }}
    .attachment-missing {{ margin-top:6px; font-size:11px; color:#b3261e; }}

    .message-footer {{
        display: flex;
        justify-content: flex-end;
        margin-top: 3px;
        font-size: 10px;
        color: var(--muted);
    }}

    .system-message {{
        max-width: 720px;
        margin: 10px auto;
        padding: 7px 10px;
        border-radius: 7px;
        background: var(--system);
        color: #54656f;
        font-size: 12px;
        text-align: center;
        box-shadow: 0 1px 1px rgba(0,0,0,.08);
        white-space: pre-wrap;
        overflow-wrap: anywhere;
    }}

    .empty {{
        text-align: center;
        margin-top: 70px;
        color: var(--muted);
    }}

    .highlight {{
        background: #ffeb3b;
        border-radius: 2px;
    }}

    @media (max-width: 600px) {{
        header {{
            padding: 10px;
        }}

        .controls {{
            width: 100%;
        }}

        input[type="search"] {{
            flex: 1;
            min-width: 0;
        }}

        .date-filter {{
            flex: 1 1 190px;
        }}

        .date-filter input[type="date"] {{
            width: 100%;
            min-width: 118px;
        }}

        .bubble {{
            max-width: 88%;
        }}

        .day-separator {{
            top: 126px;
        }}
    }}
</style>
</head>
<body>
<header>
    <div class="topbar">
        <div class="title-area">
            <h1>{safe_title}</h1>
            <small id="summary"></small>
        </div>
        <div class="controls">
            <input id="search" type="search" placeholder="Buscar na conversa">
            <label class="date-filter">
                De
                <input id="dateFrom" type="date" aria-label="Data inicial">
            </label>
            <label class="date-filter">
                Até
                <input id="dateTo" type="date" aria-label="Data final">
            </label>
            <button id="clearDatesButton" type="button" disabled>Limpar datas</button>
            <label class="option-group">
                Minhas mensagens
                <select id="meSelect">
                    <option value="">Não identificar</option>
                </select>
            </label>
            <label class="option-group">
                Minha cor
                <input id="outgoingColor" type="color" value="#d9fdd3">
            </label>
            <label class="option-group">
                Recebidas
                <input id="incomingColor" type="color" value="#ffffff">
            </label>
            <button id="orderButton" type="button">Mais novos primeiro</button>
        </div>
    </div>
</header>

<main id="chat"></main>

<script>
const messages = {data_json};
let me = {json.dumps(me, ensure_ascii=False)};
let ascending = true;
let query = "";
let dateFrom = "";
let dateTo = "";

const chat = document.getElementById("chat");
const summary = document.getElementById("summary");
const orderButton = document.getElementById("orderButton");
const searchInput = document.getElementById("search");
const dateFromInput = document.getElementById("dateFrom");
const dateToInput = document.getElementById("dateTo");
const clearDatesButton = document.getElementById("clearDatesButton");
const meSelect = document.getElementById("meSelect");
const outgoingColor = document.getElementById("outgoingColor");
const incomingColor = document.getElementById("incomingColor");

function loadParticipants() {{
    const participants = [...new Set(
        messages
            .filter(message => !message.is_system && message.sender)
            .map(message => message.sender)
    )].sort((a, b) => a.localeCompare(b, "pt-BR"));

    for (const participant of participants) {{
        const option = document.createElement("option");
        option.value = participant;
        option.textContent = participant;
        meSelect.appendChild(option);
    }}

    if (me && participants.includes(me)) {{
        meSelect.value = me;
    }} else {{
        me = "";
    }}
}}

function normalize(value) {{
    return (value || "")
        .normalize("NFD")
        .replace(/[\\u0300-\\u036f]/g, "")
        .toLowerCase();
}}

function escapeHtml(value) {{
    return (value || "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}}

function highlightText(text, rawQuery) {{
    const escaped = escapeHtml(text);
    if (!rawQuery) return escaped;

    const safeQuery = rawQuery.replace(/[.*+?^${{}}()|[\\]\\\\]/g, "\\\\$&");
    const regex = new RegExp(`(${{safeQuery}})`, "gi");
    return escaped.replace(regex, '<span class="highlight">$1</span>');
}}

function messageDay(message) {{
    if (!message.timestamp) return "";
    return message.timestamp.slice(0, 10);
}}

function formatDay(isoDay) {{
    if (!isoDay) return "";
    const [year, month, day] = isoDay.split("-");
    return `${{day}}/${{month}}/${{year}}`;
}}

function loadDateLimits() {{
    const days = messages
        .map(messageDay)
        .filter(Boolean)
        .sort((a, b) => a.localeCompare(b));

    if (!days.length) return;

    const firstDay = days[0];
    const lastDay = days[days.length - 1];
    dateFromInput.min = firstDay;
    dateFromInput.max = lastDay;
    dateToInput.min = firstDay;
    dateToInput.max = lastDay;
}}

function formatPeriod() {{
    if (!dateFrom && !dateTo) return "";
    if (dateFrom && dateTo) return ` · ${{formatDay(dateFrom)}} a ${{formatDay(dateTo)}}`;
    if (dateFrom) return ` · desde ${{formatDay(dateFrom)}}`;
    return ` · até ${{formatDay(dateTo)}}`;
}}

function render() {{
    const normalizedQuery = normalize(query);

    if (dateFrom && dateTo && dateFrom > dateTo) {{
        chat.innerHTML = '<div class="empty">A data inicial deve ser anterior ou igual à data final.</div>';
        summary.textContent = "Intervalo de datas inválido";
        clearDatesButton.disabled = false;
        return;
    }}

    let visible = messages.filter(message => {{
        const day = messageDay(message);
        const matchesStart = !dateFrom || (day && day >= dateFrom);
        const matchesEnd = !dateTo || (day && day <= dateTo);
        if (!matchesStart || !matchesEnd) return false;

        if (!normalizedQuery) return true;
        return normalize(`${{message.sender || ""}} ${{message.text}}`).includes(normalizedQuery);
    }});

    visible = [...visible].sort((a, b) => {{
        const left = a.timestamp || "";
        const right = b.timestamp || "";
        return ascending
            ? left.localeCompare(right) || a.index - b.index
            : right.localeCompare(left) || b.index - a.index;
    }});

    chat.innerHTML = "";
    summary.textContent = `${{visible.length}} de ${{messages.length}} mensagens${{formatPeriod()}}`;
    clearDatesButton.disabled = !dateFrom && !dateTo;
    orderButton.textContent = ascending
        ? "Mais novos primeiro"
        : "Mais antigos primeiro";

    if (!visible.length) {{
        chat.innerHTML = '<div class="empty">Nenhuma mensagem encontrada.</div>';
        return;
    }}

    let lastDay = null;

    for (const message of visible) {{
        const day = messageDay(message);

        if (day !== lastDay && day) {{
            const separator = document.createElement("div");
            separator.className = "day-separator";
            separator.textContent = formatDay(day);
            chat.appendChild(separator);
            lastDay = day;
        }}

        if (message.is_system) {{
            const system = document.createElement("div");
            system.className = "system-message";
            system.innerHTML = highlightText(message.text, query);
            chat.appendChild(system);
            continue;
        }}

        const outgoing = me && message.sender === me;

        const row = document.createElement("div");
        row.className = `message-row ${{outgoing ? "outgoing" : "incoming"}}`;

        const bubble = document.createElement("div");
        bubble.className = "bubble";

        const sender = document.createElement("div");
        sender.className = "sender";
        sender.textContent = message.sender || "";
        bubble.appendChild(sender);

        const body = document.createElement("div");
        body.className = "message-text";
        body.innerHTML = highlightText(message.text, query);
        bubble.appendChild(body);

        if (message.attachment_name) {{
            const box = document.createElement("div");
            box.className = "attachment";
            if (message.attachment_url) {{
                let media = null;
                if (message.attachment_type === "image") {{
                    media = document.createElement("img"); media.src = message.attachment_url; media.alt = message.attachment_name; media.loading = "lazy";
                }} else if (message.attachment_type === "video") {{
                    media = document.createElement("video"); media.src = message.attachment_url; media.controls = true; media.preload = "metadata";
                }} else if (message.attachment_type === "audio") {{
                    media = document.createElement("audio"); media.src = message.attachment_url; media.controls = true; media.preload = "metadata";
                }}
                if (media) box.appendChild(media);
                const a = document.createElement("a");
                a.href = message.attachment_url; a.target = "_blank"; a.rel = "noopener"; a.className = "attachment-link";
                a.textContent = media ? "Abrir arquivo" : "Abrir " + message.attachment_name;
                box.appendChild(a);
            }} else {{
                const missing = document.createElement("div"); missing.className = "attachment-missing";
                missing.textContent = "Anexo não encontrado: " + message.attachment_name; box.appendChild(missing);
            }}
            bubble.appendChild(box);
        }}

        const footer = document.createElement("div");
        footer.className = "message-footer";
        footer.textContent = message.display_date
            ? message.display_date.split(" ").slice(-1)[0]
            : "";
        bubble.appendChild(footer);

        row.appendChild(bubble);
        chat.appendChild(row);
    }}
}}

orderButton.addEventListener("click", () => {{
    ascending = !ascending;
    render();
    window.scrollTo({{ top: 0, behavior: "smooth" }});
}});

searchInput.addEventListener("input", event => {{
    query = event.target.value.trim();
    render();
}});

dateFromInput.addEventListener("change", event => {{
    dateFrom = event.target.value;
    render();
}});

dateToInput.addEventListener("change", event => {{
    dateTo = event.target.value;
    render();
}});

clearDatesButton.addEventListener("click", () => {{
    dateFrom = "";
    dateTo = "";
    dateFromInput.value = "";
    dateToInput.value = "";
    render();
}});

meSelect.addEventListener("change", event => {{
    me = event.target.value;
    render();
}});

outgoingColor.addEventListener("input", event => {{
    document.documentElement.style.setProperty("--outgoing", event.target.value);
}});

incomingColor.addEventListener("input", event => {{
    document.documentElement.style.setProperty("--incoming", event.target.value);
}});

loadParticipants();
loadDateLimits();
render();
</script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Converte uma exportação do WhatsApp em HTML."
    )
    parser.add_argument("input", type=Path, help="Arquivo .txt exportado pelo WhatsApp")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Arquivo HTML de saída. Padrão: mesmo nome do TXT.",
    )
    parser.add_argument(
        "--me",
        help="Nome exatamente como aparece na conversa para alinhar suas mensagens à direita.",
    )
    parser.add_argument(
        "--title",
        help="Título exibido no HTML.",
    )
    parser.add_argument(
        "--media-dir",
        type=Path,
        help="Pasta contendo as mídias/anexos do WhatsApp.",
    )
    parser.add_argument(
        "--date-order",
        choices=("dmy", "mdy"),
        default="dmy",
        help="Ordem da data no arquivo: dmy para dia/mês/ano ou mdy para mês/dia/ano.",
    )

    args = parser.parse_args()

    if not args.input.exists():
        parser.error(f"Arquivo não encontrado: {args.input}")

    if not args.input.is_file():
        parser.error(f"O caminho não é um arquivo: {args.input}")

    output = args.output or args.input.with_suffix(".html")
    title = args.title or args.input.stem

    messages = parse_export(
        args.input,
        args.date_order,
        args.media_dir,
        output_dir=output.resolve().parent,
    )

    referenced = sum(1 for m in messages if m.attachment_name)
    resolved = sum(1 for m in messages if m.attachment_url)
    missing_names = [
        m.attachment_name
        for m in messages
        if m.attachment_name and not m.attachment_url
    ]

    if not messages:
        parser.error(
            "Nenhuma mensagem foi reconhecida. Verifique o formato do arquivo exportado."
        )

    output.write_text(
        build_html(messages, title=title, me=args.me),
        encoding="utf-8",
    )

    print(f"HTML criado: {output.resolve()}")
    print("Links de anexos: calculados em relação à pasta do HTML")
    print(f"Mensagens processadas: {len(messages)}")
    media_folder = args.media_dir.resolve() if args.media_dir else args.input.resolve().parent
    media_files = (
        sum(1 for item in media_folder.rglob("*") if item.is_file())
        if media_folder.exists() and media_folder.is_dir()
        else 0
    )
    print(f"Pasta de anexos: {media_folder}")
    print(f"Arquivos existentes nessa pasta: {media_files}")
    print(f"Anexos referenciados no TXT: {referenced}")
    print(f"Anexos localizados: {resolved}")
    print(f"Anexos não localizados: {referenced - resolved}")
    if missing_names:
        print("Primeiros anexos não encontrados:")
        for name in missing_names[:5]:
            print(f"  - {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
