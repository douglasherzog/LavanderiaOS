import os
import unicodedata
from datetime import datetime

try:
    import win32print
    import win32ui  # noqa: F401 (might be useful later)
except Exception as e:  # pragma: no cover
    win32print = None

# 58mm printers are typically ~32 chars per line depending on font
MAX_CHARS = 32


def _normalize_text(s: str) -> str:
    if not s:
        return ""
    # Remove diacritics to avoid codepage issues on RAW printing
    nfkd = unicodedata.normalize("NFKD", str(s))
    s2 = "".join([c for c in nfkd if not unicodedata.combining(c)])
    # Replace newlines with spaces
    s2 = s2.replace("\r", "").replace("\n", " ")
    return s2


def _money_br(v: float) -> str:
    try:
        return ("R$ " + f"{float(v or 0):,.2f}").replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"


def _wrap(text: str, width: int = MAX_CHARS):
    words = _normalize_text(text).split()
    line = []
    length = 0
    for w in words:
        if length + (1 if line else 0) + len(w) > width:
            yield " ".join(line)
            line = [w]
            length = len(w)
        else:
            if line:
                line.append(w)
                length += 1 + len(w)
            else:
                line = [w]
                length = len(w)
    if line:
        yield " ".join(line)


def _line():
    return "-" * MAX_CHARS


def _ljust(text: str, width: int) -> str:
    return _normalize_text(text)[:width].ljust(width)


def _rjust(text: str, width: int) -> str:
    return _normalize_text(text)[:width].rjust(width)


def _pair_line(left: str, right: str, width: int = MAX_CHARS) -> str:
    left = _normalize_text(left)
    right = _normalize_text(right)
    space = max(1, width - len(left) - len(right))
    return left + (" " * space) + right


def list_printers():
    if not win32print:
        return []
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    printers = win32print.EnumPrinters(flags)
    # returns tuples; name at index 2
    return [p[2] for p in printers if len(p) > 2]


def get_default_printer_name():
    # First from env
    name = os.environ.get("PRINTER_NAME")
    if name:
        return name
    # Then system default
    if win32print:
        try:
            return win32print.GetDefaultPrinter()
        except Exception:
            pass
    return None


def _send_raw_to_printer(printer_name: str, data: bytes):
    if not win32print:
        raise RuntimeError("win32print indisponivel. Instale pywin32.")
    hPrinter = win32print.OpenPrinter(printer_name)
    try:
        hJob = win32print.StartDocPrinter(hPrinter, 1, ("Ordem de Servico", None, "RAW"))
        try:
            win32print.StartPagePrinter(hPrinter)
            win32print.WritePrinter(hPrinter, data)
            win32print.EndPagePrinter(hPrinter)
        finally:
            win32print.EndDocPrinter(hPrinter)
    finally:
        win32print.ClosePrinter(hPrinter)


def build_order_receipt_text(order) -> str:
    lines = []
    # Header
    lines.append(_normalize_text("LAVANDERIA"))
    lines.append(_line())
    lines.append(_pair_line(f"OS #{order.id}", order.created_at.strftime("%d/%m/%Y %H:%M")))
    try:
        client_name = order.client.name if order.client else "Cliente"
    except Exception:
        client_name = "Cliente"
    lines.extend(_wrap(f"Cliente: {client_name}"))
    lines.append(_line())

    # Items
    total_items = 0.0
    for it in getattr(order, 'items', []) or []:
        svc = getattr(it, 'service', None)
        svc_name = getattr(svc, 'name', '') or ''
        for w in _wrap(svc_name):
            lines.append(w)
        qty = it.quantity or 0
        unit = _money_br(it.unit_price)
        sub = float(it.subtotal or 0.0)
        total_items += sub
        lines.append(_pair_line(f"Qtd {qty} x {unit}", _money_br(sub)))
    lines.append(_line())

    # Discounts/surcharges
    disc_fixed = float(getattr(order, 'discount', 0.0) or 0.0)
    disc_perc = float(getattr(order, 'discount_percent', 0.0) or 0.0)
    sur_fixed = float(getattr(order, 'surcharge', 0.0) or 0.0)
    sur_perc = float(getattr(order, 'surcharge_percent', 0.0) or 0.0)
    if disc_fixed:
        lines.append(_pair_line("Desconto", _money_br(disc_fixed)))
    if disc_perc:
        lines.append(_pair_line("Desc %", f"{disc_perc:.0f}%"))
    if sur_fixed:
        lines.append(_pair_line("Acréscimo", _money_br(sur_fixed)))
    if sur_perc:
        lines.append(_pair_line("Acrésc %", f"{sur_perc:.0f}%"))

    # Totals
    grand = float(getattr(order, 'total', 0.0) or 0.0)
    lines.append(_pair_line("Total Geral", _money_br(grand)))

    # Payments
    try:
        paid = sum(float(p.amount or 0.0) for p in getattr(order, 'payments', []) or [])
    except Exception:
        paid = 0.0
    remaining = max(0.0, grand - paid)
    lines.append(_pair_line("Pago", _money_br(paid)))
    lines.append(_pair_line("Restante", _money_br(remaining)))

    # Delivery date
    try:
        if getattr(order, 'delivery_date', None):
            lines.append(_pair_line("Entrega", order.delivery_date.strftime("%d/%m/%Y")))
    except Exception:
        pass

    lines.append(_line())
    lines.extend(_wrap("Obrigado pela preferencia!"))

    # Feed a few lines for tear
    lines.append("")
    lines.append("")
    lines.append("")

    # Join with CRLF
    return ("\r\n".join(lines) + "\r\n")


def print_order_receipt(order, printer_name: str | None = None):
    printer_name = printer_name or get_default_printer_name()
    if not printer_name:
        available = list_printers()
        raise RuntimeError(
            "Nenhuma impressora configurada. Defina PRINTER_NAME no ambiente. "
            f"Disponiveis: {available}"
        )
    text = build_order_receipt_text(order)
    # Encode to cp1252 to preserve R$, cedilha etc., best effort
    data = text.encode("cp1252", errors="ignore")
    # ESC/POS initialize + text + feed + (no cut to be safe on 58mm)
    esc_init = b"\x1b@"  # Initialize
    feed = b"\n\n\n"
    payload = esc_init + data + feed
    _send_raw_to_printer(printer_name, payload)
