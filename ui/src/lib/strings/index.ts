/**
 * Interface strings in both languages.
 *
 * The Chinese dictionaries define the shape; the English ones are typed
 * against them, so a key that exists in one language and not the other is a
 * compile error. `core` holds the strings that were in one file historically;
 * the other modules hold the strings that used to be written inline in the
 * area they are named after.
 */
import { zh as coreZh } from "./core.zh";
import { en as coreEn } from "./core.en";
import * as toolCards from "./toolCards";
import * as libs from "./libs";
import * as crystal from "./crystal";
import * as shell from "./shell";

export const zh = {
  ...coreZh,
  toolCards: toolCards.zh,
  libs: libs.zh,
  crystal: crystal.zh,
  shell: shell.zh,
};

export const en: typeof zh = {
  ...coreEn,
  toolCards: toolCards.en,
  libs: libs.en,
  crystal: crystal.en,
  shell: shell.en,
};

export type Strings = typeof zh;
