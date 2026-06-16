import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export interface ParsedMessage {
  thinkBlocks: string[];
  answer: string;
}

export function parseThinkBlocks(raw: string): ParsedMessage {
  const thinkBlocks: string[] = [];
  const regex = /<think>([\s\S]*?)<\/think>/g;
  let match;
  while ((match = regex.exec(raw)) !== null) {
    const content = match[1].trim();
    if (content) thinkBlocks.push(content);
  }
  const answer = raw.replace(/<think>[\s\S]*?<\/think>/g, "").trim();
  return { thinkBlocks, answer };
}
