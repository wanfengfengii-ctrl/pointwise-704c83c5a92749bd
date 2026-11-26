from dataclasses import dataclass
from html import escape


@dataclass(frozen=True, slots=True)
class PageResponse:
    status: int
    body: str


def page(title: str, content: str, status: int = 200) -> PageResponse:
    return PageResponse(status, f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} · 榆巷纸样工坊</title>
<link rel="stylesheet" href="/style.css">
</head>
<body>
<header class="site-header"><a href="/">榆巷纸样工坊</a></header>
<main>
<h1>{escape(title)}</h1>
{content}
</main>
</body>
</html>''')


def problem(status: int, message: str) -> PageResponse:
    return page('请求未完成', f'<p role="alert">{escape(message)}</p>', status)
