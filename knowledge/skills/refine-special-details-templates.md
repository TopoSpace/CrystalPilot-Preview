---
name: refine-special-details-templates
description: _refine_special_details 无序描述模板库（Nat. Chem. 审稿人亲自给出的范式+作者实答）：无序溶剂/无序基团/整分子共位无序三类模板句、占有率竞争精修的表述与"竞争测试"义务、失败结果也要写进描述。write_outputs 前为每处无序写描述时按此填空。
alerts: []
tools: [write_outputs, model_disorder, run_shelxl, set_restraints]
tags: [精修描述, 无序, CIF, refine_special_details, 审稿, 模板]
source: matstr.com tid 1368（Nat. Chem. 2024, 16, 1788–1793, DOI 10.1038/s41557-024-01597-8，经论文作者同意公开的完整审稿往还；全文转录见语料 threads/2025-6-10_1368_*/supplement.md）
confidence: high
created_by: mentor
---

# _refine_special_details 无序描述模板库

## 审稿人的期望（原文）

"a more complete description of the disorder modelling should include in
the _refine_special_details section of the CIF" —— 结构判定正确不豁免描述
义务；该审稿人对每个含无序的结构逐一要求补描述，并**亲自写了范文**。

## 模板 A：无序溶剂分子（审稿人范文，照此填空）

> The {toluene} solvent molecule is disordered over two orientations.
> The occupancies of the two disorder components were refined
> competitively converging to a ratio of {0.618(9):0.382(9)}. Aromatic
> C-C 1,2- and 1,3-distances of the {toluene} molecules were restrained
> to be approximately equal (as well as the Me-C 1,2- and
> 1,3-distances). Each {toluene} molecule was restrained to
> approximately flat geometry. Rigid bond and similarity restraints
> were applied to the anisotropic displacement parameters of the
> disordered atoms.

要素清单：①无序对象与取向数；②占有率**竞争精修**收敛值（带 su）；
③几何限制逐条（1,2-/1,3-等距、FLAT）；④ADP 限制（RIGU/SIMU=rigid
bond and similarity）。

## 模板 B：无序基团（-OPh 等）

> The {OPh} group is disordered over two positions. All equivalent
> 1,2- and 1,3-distances were restrained to be approximately equal.
> The occupancies of the two disorder components were refined
> competitively converging to a ratio of {0.869(3):0.131(3)}. Rigid
> bond and similarity restraints were applied to the anisotropic
> displacement parameters of the disordered atoms.

## 模板 C：整分子共位无序（两种配合物占同一位置）

> The asymmetric unit contains two different complex molecules
> disordered at the same position. The two alternative complex
> molecules were refined with occupation factors of {0.518(10)} for
> {[Pd(CSiMe3)(PNP)]*N2} and {0.482(10)} for {[PdC(N2)SiMe3(PNP)]}.
> Rigid bond and similarity restraints were applied to the anisotropic
> displacement parameters of the disordered atoms. The {N-N} distance
> of the {N2} molecule is restrained to approximately {1.1} Å.

## 占有率"竞争测试"义务（5b 案）

审稿人可要求**解开占有率耦合单独竞争精修**以证明模型选择正确
（"this should be tested by separate competitive refinement... Whether
it is or not, this needs to be tested, and the result included"）。
作者实答示范了失败结果的诚实写法：解耦精修给出不合理结果并触发
330_ALERT_2_A（苯环平均 C-C 1.44 Å），两个过近组分占有率同时膨胀
（0.59/0.54），**把这个失败测试连同数字写进 ESI 与描述**，然后保留
耦合模型。教训：审稿人要的不是某个结论，而是"测过并报告"。

## CrystalPilot 落点

- write_outputs 装配的 `_refine_special_details` 默认只写平台声明；
  每处无序应把上述模板填空后并入 summary_note/VALIDATION.md，或在
  交付说明中给出（描述与 set_restraints 实际所加限制逐条对应，
  写了 restrained 就必须真有那条限制，反之亦然）。
- 占有率数值一律引用 run_shelxl(adopt) 后带 su 的收敛值，不用
  refine 内核的无 su 值。
