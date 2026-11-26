import type { TFunction } from "i18next";

/** Turn backend messages (English, sometimes technical) into friendly, translated text. */
export function friendlyError(raw: unknown, t: TFunction): string {
  const msg = raw instanceof Error ? raw.message : String(raw ?? "");
  const rules: [RegExp, (m: RegExpMatchArray) => string][] = [
    [/No manuscript found|no root \.tex file/i, () => t("errors.noManuscript")],
    [/full path of an existing folder|absolute path/i, () => t("errors.localPath")],
    [/No model configured/i, () => t("errors.noModel")],
    [/file type not supported: (.+)/i, (m) => t("errors.fileType", { name: m[1] })],
    [/upload too large|archive too large/i, () => t("errors.tooLarge")],
    [/not a valid \.zip/i, () => t("errors.badZip")],
    [/several (possible main|candidate root) files?:?\s*(.*)/i, (m) => t("errors.severalMains", { files: m[2].replace(/\. Upload.*$/, "") })],
    [/already in progress/i, () => t("run.alreadyRunning")],
    [/project not found|invalid project id/i, () => t("errors.projectMissing")],
    [/damaged|pandoc failed|couldn't unpack/i, () => t("errors.damaged")],
    [/pandoc is required|pandoc not found/i, () => t("status.pandocMissing")],
    [/could not be read; it may be damaged/i, () => t("errors.badPdf")],
    [/no extractable text/i, () => t("errors.scannedPdf")],
    [/maximum cost/i, () => t("errors.budget")],
    [/no results yet|run a check first/i, () => t("project.notChecked")],
    [/the file is not a PDF/i, () => t("errors.notPdf")],
    [/AuthenticationError|invalid x-api-key|api key/i, () => t("errors.auth")],
  ];
  for (const [re, fn] of rules) {
    const m = msg.match(re);
    if (m) return fn(m);
  }
  return msg || t("app.error");
}

/** Notices written by the backend in English. */
export function translateNotice(msg: string, t: TFunction): string {
  let m = msg.match(/internal checks: (\d+) of (\d+) uncited statements selected/);
  if (m) return t("notices.internal", { kept: m[1], total: m[2] });
  m = msg.match(/(\d+) unit\(s\) were verified with another model/);
  if (m) return t("notices.staleModel", { count: Number(m[1]) });
  if (/context window/.test(msg)) return t("notices.contextWindow");
  return msg;
}
