export type CaretOffsets = { start: number; end: number };

/** Character offsets of the current selection, counted through the visible text. */
export function selectionOffsets(root: HTMLElement): CaretOffsets | null {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0) return null;
  const range = selection.getRangeAt(0);
  if (!root.contains(range.startContainer) || !root.contains(range.endContainer)) return null;
  return {
    start: endpointOffset(root, range.startContainer, range.startOffset),
    end: endpointOffset(root, range.endContainer, range.endOffset),
  };
}

export function readEditorText(root: HTMLElement): string {
  return (root.textContent ?? "").replace(/\u00a0/g, " ");
}

/** Put the caret or selection back after the highlighted markup is rebuilt. */
export function setSelectionOffsets(root: HTMLElement, start: number, end: number): void {
  const selection = window.getSelection();
  if (!selection) return;
  const length = (root.textContent ?? "").length;
  const safeStart = clamp(start, length);
  const safeEnd = clamp(end, length);
  const range = document.createRange();
  const startPoint = pointAt(root, Math.min(safeStart, safeEnd));
  const endPoint = pointAt(root, Math.max(safeStart, safeEnd));
  range.setStart(startPoint.node, startPoint.offset);
  range.setEnd(endPoint.node, endPoint.offset);
  selection.removeAllRanges();
  selection.addRange(range);
}

function clamp(offset: number, length: number): number {
  return Math.max(0, Math.min(length, offset));
}

function endpointOffset(root: HTMLElement, container: Node, offset: number): number {
  const range = document.createRange();
  range.selectNodeContents(root);
  range.setEnd(container, offset);
  return range.toString().length;
}

function pointAt(root: HTMLElement, offset: number): { node: Node; offset: number } {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let remaining = offset;
  let last: Text | null = null;
  while (walker.nextNode()) {
    const current = walker.currentNode as Text;
    last = current;
    if (remaining <= current.data.length) return { node: current, offset: remaining };
    remaining -= current.data.length;
  }
  if (last) return { node: last, offset: last.data.length };
  return { node: root, offset: 0 };
}
