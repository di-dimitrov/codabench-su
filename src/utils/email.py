import logging
import re
from html.parser import HTMLParser

import nh3
import markdown
from django.conf import settings
from django.contrib.sites.models import Site
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def get_link_context(request=None):
    """
    Build the {domain, protocol} pair used for absolute links in email templates.

    Pass `request` when one is available so the scheme matches how the user
    actually connected (relevant behind a reverse proxy terminating TLS).
    Omit it (e.g. from a model method with no request in scope) and it
    defaults to 'https', since production is HTTPS-only.
    """
    return {
        'domain': settings.DOMAIN_NAME,
        'protocol': 'https' if request is None or request.is_secure() else 'http',
    }


def codalab_send_mail(context_data, to_email, html_file, text_file, subject, from_email=None):
    from_email = from_email if from_email else settings.DEFAULT_FROM_EMAIL

    context_data["site"] = Site.objects.get_current()

    text = render_to_string(text_file, context_data)
    html = render_to_string(html_file, context_data)
    to_email = to_email if type(to_email) is list else [to_email]
    message = EmailMultiAlternatives(subject, text, from_email=from_email, to=to_email)
    message.attach_alternative(html, 'text/html')
    message.send()


class EmailDeliveryError(Exception):
    """Raised after a bulk send when at least one batch of recipients could not be delivered."""


# What an organizer can write in the editor (EasyMDE / GitHub-flavoured markdown) and have kept in the email.
# Anything else (scripts, styles, forms, event handlers, javascript: links, ...) is removed.
EMAIL_ALLOWED_TAGS = {
    'a', 'abbr', 'b', 'blockquote', 'br', 'code', 'del', 'em', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr',
    'i', 'img', 'ins', 'li', 'ol', 'p', 'pre', 's', 'strong', 'sub', 'sup', 'table', 'tbody', 'td', 'tfoot',
    'th', 'thead', 'tr', 'u', 'ul',
}
EMAIL_ALLOWED_ATTRIBUTES = {
    'a': {'href', 'title'},
    'img': {'src', 'alt', 'title', 'width', 'height'},
    'td': {'align'},
    'th': {'align'},
    'ol': {'start'},
}
EMAIL_ALLOWED_URL_SCHEMES = {'http', 'https', 'mailto'}

# Mail clients do not load the site's stylesheets, so the few things markdown relies on to look right
# (table borders, code blocks, quotes, image size) are styled here.
EMAIL_HTML_STYLE = (
    'body{font-family:-apple-system,"Segoe UI",Helvetica,Arial,sans-serif;font-size:14px;line-height:1.5;color:#222;}'
    'table{border-collapse:collapse;}'
    'th,td{border:1px solid #ccc;padding:4px 8px;text-align:left;}'
    'th{background:#f2f2f2;}'
    'pre{background:#f6f8fa;border:1px solid #e1e4e8;padding:8px;overflow:auto;}'
    'code{font-family:Consolas,Menlo,monospace;}'
    'blockquote{border-left:4px solid #ddd;margin:0 0 1em 0;padding:0 0 0 12px;color:#555;}'
    'img{max-width:100%;height:auto;}'
)


def _absolute_url_filter(link_context):
    """Mail clients cannot resolve '/competitions/1/' links, so make site-relative links absolute."""
    base = f"{link_context['protocol']}://{link_context['domain']}"

    def attribute_filter(tag, attribute, value):
        if attribute in ('href', 'src') and value.startswith('/') and not value.startswith('//'):
            return base + value
        return value

    return attribute_filter


def render_email_html(content):
    """
    Turn what an organizer wrote into the HTML body of an email.

    `content` is either HTML already rendered by the editor (what the competition page sends, so the email is
    exactly what the organizer saw in the preview) or raw markdown (what API clients can send). Python-Markdown
    leaves block-level HTML untouched and renders anything else, so both go through the same call.
    The result is always sanitized on the server; the browser-side sanitizing can be bypassed by calling the API.
    """
    html = markdown.markdown(content or '', extensions=['tables', 'fenced_code', 'sane_lists'])
    html = nh3.clean(
        html,
        tags=EMAIL_ALLOWED_TAGS,
        attributes=EMAIL_ALLOWED_ATTRIBUTES,
        url_schemes=EMAIL_ALLOWED_URL_SCHEMES,
        attribute_filter=_absolute_url_filter(get_link_context()),
    )
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        f'<style>{EMAIL_HTML_STYLE}</style></head><body>{html}</body></html>'
    )


class _PlainTextExtractor(HTMLParser):
    """Minimal HTML -> text converter used for the plain-text alternative of an email."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.chunks = []
        self.trailing_newlines = 0
        self.lists = []          # one [ordered, counter] entry per open <ul>/<ol>
        self.links = []          # one (href, chunk index) entry per open <a>
        self.quotes = []         # chunk index where each open <blockquote> started
        self.pre_depth = 0
        self.cell_index = 0
        self.after_bullet = False  # a list marker was just written, so a <p> inside the item stays on its line

    def emit(self, text):
        if not text:
            return
        self.after_bullet = False
        self.chunks.append(text)
        stripped = text.rstrip('\n')
        if stripped:
            self.trailing_newlines = len(text) - len(stripped)
        else:
            self.trailing_newlines += len(text)

    def line_break(self, count=1):
        if self.chunks and self.trailing_newlines < count:
            self.emit('\n' * (count - self.trailing_newlines))

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'br':
            self.emit('\n')
        elif tag in ('p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'table', 'blockquote', 'pre'):
            if not self.after_bullet:
                self.line_break(2)
            if tag == 'blockquote':
                self.quotes.append(len(self.chunks))
            elif tag == 'pre':
                self.pre_depth += 1
        elif tag == 'hr':
            self.line_break(2)
            self.emit('----')
            self.line_break(2)
        elif tag in ('ul', 'ol'):
            self.line_break(1 if self.lists else 2)
            start = attrs.get('start') or ''
            self.lists.append([tag == 'ol', int(start) if start.isdigit() else 1])
        elif tag == 'li':
            self.line_break(1)
            indent = '  ' * max(len(self.lists) - 1, 0)
            if self.lists and self.lists[-1][0]:
                self.emit(f'{indent}{self.lists[-1][1]}. ')
                self.lists[-1][1] += 1
            else:
                self.emit(f'{indent}- ')
            self.after_bullet = True
        elif tag == 'tr':
            self.line_break(1)
            self.cell_index = 0
        elif tag in ('td', 'th'):
            if self.cell_index:
                self.emit(' | ')
            self.cell_index += 1
        elif tag == 'a':
            self.links.append((attrs.get('href') or '', len(self.chunks)))
        elif tag == 'img':
            alt = attrs.get('alt') or 'image'
            self.emit(f"[{alt}] {attrs.get('src') or ''}".rstrip())

    def handle_endtag(self, tag):
        if tag in ('p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'table'):
            self.line_break(2)
        elif tag == 'pre':
            self.pre_depth = max(self.pre_depth - 1, 0)
            self.line_break(2)
        elif tag in ('ul', 'ol'):
            if self.lists:
                self.lists.pop()
            self.line_break(1 if self.lists else 2)
        elif tag == 'blockquote' and self.quotes:
            start = self.quotes.pop()
            quoted = ''.join(self.chunks[start:]).strip('\n')
            del self.chunks[start:]
            self.trailing_newlines = 0
            self.emit('\n'.join(f'> {line}'.rstrip() for line in quoted.split('\n')))
            self.line_break(2)
        elif tag == 'a' and self.links:
            href, start = self.links.pop()
            label = ''.join(self.chunks[start:]).strip()
            if href and href != label and href.replace('mailto:', '', 1) != label:
                self.emit(f' ({href})')

    def handle_data(self, data):
        if self.pre_depth:
            self.emit(data)
            return
        data = re.sub(r'\s+', ' ', data)
        if self.trailing_newlines or not self.chunks or self.after_bullet:
            data = data.lstrip()
        self.emit(data)


def html_to_text(html):
    """Plain-text alternative of an HTML email body (for clients, filters and screen readers that skip HTML)."""
    html = re.sub(r'(?is)<(style|script|head)\b.*?</\1>', '', html)
    extractor = _PlainTextExtractor()
    extractor.feed(html)
    extractor.close()
    text = ''.join(extractor.chunks)
    text = re.sub(r'[ \t]+\n', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip() + '\n'


def unique_email_addresses(addresses):
    """Strip, drop blanks and remove case-insensitive duplicates while keeping the original order."""
    seen, unique = set(), []
    for address in addresses or []:
        address = (address or '').strip()
        if address and address.lower() not in seen:
            seen.add(address.lower())
            unique.append(address)
    return unique


def codalab_send_markdown_email(subject, markdown_content, recipient_list, from_email=None):
    """
    Send one message with the same body to many recipients without revealing who they are.

    Recipients are only ever put in BCC (which Django leaves out of the message headers) and the message has no
    `To` at all, so no address, not even our own sender address, receives an extra copy. They are sent in batches
    of settings.EMAIL_BULK_BATCH_SIZE, so providers' per-message recipient limits are respected and one rejected
    batch does not stop the others. A lone recipient (a direct message to one participant) is addressed normally,
    since the only address they could see is their own.

    `markdown_content` may be markdown or the HTML rendered by the editor, see `render_email_html`.
    Returns the number of recipients; raises EmailDeliveryError if some batches could not be sent.
    """
    from_email = from_email if from_email else settings.DEFAULT_FROM_EMAIL
    recipients = unique_email_addresses(recipient_list)
    if not recipients:
        logger.warning('Not sending "%s": no recipients', subject)
        return 0

    html_body = render_email_html(markdown_content)
    text_body = html_to_text(html_body)
    batch_size = max(int(getattr(settings, 'EMAIL_BULK_BATCH_SIZE', 100)), 1)

    failed = 0
    for start in range(0, len(recipients), batch_size):
        batch = recipients[start:start + batch_size]
        addressing = {'to': batch} if len(batch) == 1 else {'bcc': batch}
        message = EmailMultiAlternatives(subject, text_body, from_email=from_email, **addressing)
        message.attach_alternative(html_body, 'text/html')
        try:
            message.send()
        except Exception:
            failed += len(batch)
            logger.exception('Could not send "%s" to %d recipients (batch starting at %d)', subject, len(batch), start)

    if failed:
        raise EmailDeliveryError(f'"{subject}" could not be delivered to {failed} of {len(recipients)} recipients')
    logger.info('Sent "%s" to %d recipients', subject, len(recipients))
    return len(recipients)
