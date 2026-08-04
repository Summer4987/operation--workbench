(function initContractFormat(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.ContractFormat = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function contractFormatFactory() {
  function escapeHtml(value) {
    return String(value || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function normalizeContractText(text) {
    return String(text || "")
      .replace(/\r\n?/g, "\n")
      .replace(/\u00a0/g, " ")
      .replace(/([。；])(?=\d{1,2}\.\d+)/g, "$1\n")
      .replace(/[ \t]{2,}(?=(?:\d{1,2}\.\d+|[（(][一二三四五六七八九十0-9]+[）)]|第[一二三四五六七八九十0-9]+条|附件[一二三四五六七八九十0-9]+[：:]))/g, "\n");
  }

  function paragraphHtml(line) {
    const text = line.trim();
    if (!text) return "";
    const safe = escapeHtml(text);
    if (/^━{6,}$/.test(text)) return '<div class="page-break"></div>';
    if (/^(服务合同|采购框架协议|协议书)$/.test(text)) {
      const pageBreak = text === "采购框架协议" ? " page-break-before" : "";
      return `<h1 class="part-title${pageBreak}">${safe}</h1>`;
    }
    if (/^第[一二三四五六七八九十0-9]+条/.test(text) || /^附件[一二三四五六七八九十0-9]+[：:]/.test(text)) {
      return `<h2>${safe}</h2>`;
    }
    if (/^[（(][一二三四五六七八九十0-9]+[）)]/.test(text)) {
      return `<p class="list-item">${safe}</p>`;
    }
    if (/^(甲方|乙方|法定代表人|联系地址|联系电话|签订日期|日期|收件人|电子邮箱|邮寄地址|统一社会信用代码|地址|联系方式)[（(：:]/.test(text)) {
      return `<p class="field-line">${safe}</p>`;
    }
    if (/^（以下无正文）$/.test(text)) return `<p class="no-body">${safe}</p>`;
    return `<p>${safe}</p>`;
  }

  function contractBodyHtml(text) {
    return normalizeContractText(text)
      .split("\n")
      .map(paragraphHtml)
      .filter(Boolean)
      .join("\n");
  }

  function wordHtml(title, text) {
    return `<!doctype html><html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word"><head><meta charset="utf-8"><title>${escapeHtml(title)}</title>
    <style>
      @page{size:A4;margin:2.4cm 2.2cm}
      body{font-family:"Arial Unicode MS","Songti SC","Microsoft YaHei","SimSun","宋体",serif;font-size:12pt;line-height:1.65;color:#000}
      h1.document-title,h1.part-title{text-align:center;font-family:"Arial Unicode MS","STHeiti","Microsoft YaHei","SimHei","黑体",sans-serif;font-size:20pt;font-weight:bold;margin:0 0 22pt;line-height:1.35}
      h1.part-title{font-size:18pt;margin-top:8pt}
      h2{font-family:"Arial Unicode MS","STHeiti","Microsoft YaHei","SimHei","黑体",sans-serif;font-size:14pt;font-weight:bold;margin:16pt 0 8pt;line-height:1.45;page-break-after:avoid}
      p{margin:0 0 7pt;text-align:justify;text-justify:inter-ideograph;text-indent:2em;line-height:1.65}
      p.field-line{margin-bottom:6pt;text-indent:0}
      p.list-item{margin-left:2em;text-indent:-2em}
      p.no-body{text-align:center;text-indent:0;margin:20pt 0}
      .page-break,.page-break-before{page-break-before:always}
      .contract-body{mso-line-height-rule:exactly}
    </style>
    </head><body><h1 class="document-title">${escapeHtml(title)}</h1><div class="contract-body">${contractBodyHtml(text)}</div></body></html>`;
  }

  return { contractBodyHtml, normalizeContractText, wordHtml };
});
