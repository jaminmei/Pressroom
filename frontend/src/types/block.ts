/** A single detected block from layout detection engine output. */
export interface Block {
  id: string;
  type: string;
  bbox: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
  confidence: number;
  page_number?: number;
}
