/**
 * 安全的最小 Markdown 渲染（ADR-16/XSS）：
 * - 所有文本段先转义 HTML，再套用行内标记——用户/LLM 文本永远不可能注入标签；
 * - 链接仅放行 `/`（非 `//`）与 `https?://`；`javascript:`、`data:`、协议相对一律拒收。
 */

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function safeHref(href: string): string | null {
  const trimmed = href.trim()
  if (!trimmed) return null
  if (trimmed.startsWith('/')) {
    return trimmed.startsWith('//') ? null : trimmed
  }
  if (/^https?:\/\//i.test(trimmed)) return trimmed
  return null
}

/** 行内标记：链接/粗体/斜体/行内代码。输入是**未转义**文本，输出安全 HTML。 */
function inline(text: string): string {
  // 先按行内代码切分——代码段内不再解释其他标记。
  const parts = text.split(/(`[^`\n]*`)/g)
  return parts
    .map((part) => {
      if (part.length >= 2 && part.startsWith('`') && part.endsWith('`')) {
        return `<code>${escapeHtml(part.slice(1, -1))}</code>`
      }
      return inlineNoCode(part)
    })
    .join('')
}

function inlineNoCode(text: string): string {
  // 链接先提取占位，避免标签文本里的 * 被斜体规则吃掉。
  const links: string[] = []
  // 剥离用户/LLM 文本中的 \u0001，防止伪造占位符。
  const cleaned = text.replace(/\u0001/g, '')
  let working = cleaned.replace(/\[([^\]\n]*)\]\(([^)\s]+)\)/g, (_m, label: string, href: string) => {
    const safe = safeHref(href)
    if (safe === null) {
      links.push(escapeHtml(label))
    } else {
      const external = /^https?:\/\//i.test(safe)
        ? ' target="_blank" rel="noopener noreferrer"'
        : ''
      links.push(`<a href="${escapeHtml(safe)}"${external}>${escapeHtml(label)}</a>`)
    }
    return `\u0001LINK${links.length - 1}\u0001`
  })
  let html = escapeHtml(working)
  html = html.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>')
  html = html.replace(/\u0001LINK(\d+)\u0001/g, (_m, i: string) => links[Number(i)] ?? '')
  return html
}

function renderTable(rows: string[]): string {
  const cells = (line: string) =>
    line
      .replace(/^\|/, '')
      .replace(/\|$/, '')
      .split('|')
      .map((c) => c.trim())
  const head = cells(rows[0])
  const body = rows.slice(2).map(cells)
  const th = head.map((c) => `<th>${inline(c)}</th>`).join('')
  const trs = body
    .map((r) => `<tr>${r.map((c) => `<td>${inline(c)}</td>`).join('')}</tr>`)
    .join('')
  return `<table><thead><tr>${th}</tr></thead><tbody>${trs}</tbody></table>`
}

function isTableDivider(line: string): boolean {
  return /^\|?[\s:|-]+\|?$/.test(line) && line.includes('-')
}

export function renderSafeMarkdown(source: string): string {
  const lines = source.replace(/\r\n/g, '\n').split('\n')
  const out: string[] = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    //  fenced code block
    if (/^```/.test(line.trimStart())) {
      const lang = line.trim().slice(3).trim()
      const buf: string[] = []
      i++
      while (i < lines.length && !/^```/.test(lines[i].trimStart())) {
        buf.push(lines[i])
        i++
      }
      i++ // skip closing fence
      const cls = lang ? ` class="lang-${escapeHtml(lang)}"` : ''
      out.push(`<pre><code${cls}>${escapeHtml(buf.join('\n'))}</code></pre>`)
      continue
    }
    // heading
    const heading = line.match(/^(#{1,3})\s+(.*)$/)
    if (heading) {
      const level = heading[1].length + 2 // h3-h5，避免与页面 h1/h2 争层级
      out.push(`<h${level}>${inline(heading[2])}</h${level}>`)
      i++
      continue
    }
    // table
    if (
      line.includes('|') &&
      i + 1 < lines.length &&
      isTableDivider(lines[i + 1]) &&
      line.trim().startsWith('|')
    ) {
      const rows = [line, lines[i + 1]]
      i += 2
      while (i < lines.length && lines[i].trim().startsWith('|') && lines[i].includes('|')) {
        rows.push(lines[i])
        i++
      }
      out.push(renderTable(rows))
      continue
    }
    // lists
    if (/^\s*[-*]\s+/.test(line)) {
      const items: string[] = []
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*]\s+/, ''))
        i++
      }
      out.push(`<ul>${items.map((it) => `<li>${inline(it)}</li>`).join('')}</ul>`)
      continue
    }
    if (/^\s*\d+[.)]\s+/.test(line)) {
      const items: string[] = []
      while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*\d+[.)]\s+/, ''))
        i++
      }
      out.push(`<ol>${items.map((it) => `<li>${inline(it)}</li>`).join('')}</ol>`)
      continue
    }
    // blank / paragraph
    if (!line.trim()) {
      i++
      continue
    }
    const para: string[] = [line]
    i++
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^(#{1,3})\s+/.test(lines[i]) &&
      !/^```/.test(lines[i].trimStart()) &&
      !/^\s*[-*]\s+/.test(lines[i]) &&
      !/^\s*\d+[.)]\s+/.test(lines[i])
    ) {
      para.push(lines[i])
      i++
    }
    out.push(`<p>${inline(para.join('\n')).replace(/\n/g, '<br>')}</p>`)
  }
  return out.join('\n')
}
