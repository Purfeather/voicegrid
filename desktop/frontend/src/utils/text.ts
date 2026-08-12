export function splitText(value: string, maxChars: number): string[] {
  const text = value.replace(/\r\n?/g, "\n").trim();
  if (!text) return [];
  const limit = Math.max(20, maxChars);
  const units = text.split(/(?<=[。！？!?；;：:\n])/u).filter(Boolean);
  const result: string[] = [];
  let current = "";

  for (let unit of units.map((item) => item.trim()).filter(Boolean)) {
    while (unit.length > limit) {
      if (current) {
        result.push(current);
        current = "";
      }
      let cut = Math.max(unit.lastIndexOf("，", limit), unit.lastIndexOf(",", limit));
      if (cut < limit / 2) cut = limit;
      else cut += 1;
      result.push(unit.slice(0, cut).trim());
      unit = unit.slice(cut).trim();
    }
    if (!current) current = unit;
    else if (current.length + unit.length <= limit) current += unit;
    else {
      result.push(current);
      current = unit;
    }
  }
  if (current) result.push(current);
  return result;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (!seconds || !Number.isFinite(seconds)) return "00:00";
  const minutes = Math.floor(seconds / 60);
  const rest = Math.floor(seconds % 60);
  return `${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
}
