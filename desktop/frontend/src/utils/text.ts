export const PAUSE_MARKER = "[pause 1.0s]";
export const PAUSE_MARKER_PATTERN = /\[pause\s+(\d+(?:\.\d+)?)s\]/gu;

function protectPauseMarkers(value: string): { text: string; markers: Map<string, string> } {
  const markers = new Map<string, string>();
  const text = value.replace(PAUSE_MARKER_PATTERN, (marker) => {
    for (let codepoint = 0xe000; codepoint <= 0xf8ff; codepoint += 1) {
      const token = String.fromCharCode(codepoint);
      if (!value.includes(token) && !markers.has(token)) {
        markers.set(token, marker);
        return token;
      }
    }
    throw new Error("停顿标记数量过多，无法安全切分文本。");
  });
  return { text, markers };
}

export function countSpokenCharacters(value: string): number {
  return value.replace(PAUSE_MARKER_PATTERN, "").trim().length;
}

export function insertPauseMarker(value: string, position: number | null): { value: string; cursor: number } {
  const insertion = position === null ? value.length : Math.max(0, Math.min(value.length, position));
  return {
    value: `${value.slice(0, insertion)}${PAUSE_MARKER}${value.slice(insertion)}`,
    cursor: insertion + PAUSE_MARKER.length,
  };
}

export function splitText(value: string, maxChars: number): string[] {
  const normalized = value.replace(/\r\n?/g, "\n").trim();
  if (!normalized) return [];
  const protectedText = protectPauseMarkers(normalized);
  const text = protectedText.text;
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
  return result.map((segment) => Array.from(segment, (character) => protectedText.markers.get(character) ?? character).join(""));
}

export function formatDuration(seconds: number | null | undefined): string {
  if (!seconds || !Number.isFinite(seconds)) return "00:00";
  const minutes = Math.floor(seconds / 60);
  const rest = Math.floor(seconds % 60);
  return `${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
}
