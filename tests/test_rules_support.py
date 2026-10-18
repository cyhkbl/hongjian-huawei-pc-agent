"""Fake KB for rules unit tests. No real KB content, no copyright issues."""
from __future__ import annotations

from typing import Optional

from app.models import (
    Fact, ImageAsset, KBStatus, PriceRecord, ProductModel, SearchHit, TraceEntry,
)


class FakeKB:
    """Minimal KB for testing understand/compliance/verify without real KB data."""
    
    def __init__(self):
        self._models = [
            ProductModel(
                model_id="mb14-hm",
                name="HUAWEI MateBook 14（鸿蒙版）",
                short_name="MateBook 14 鸿蒙版",
                series="MateBook 14",
                os_family="harmonyos",
                os_label="HarmonyOS 6",
                aliases=["MateBook 14 鸿蒙版", "MateBook 14 HM", "MB14鸿蒙"],
                confusable_with=["mb14-ultra"],
                has_public_price=True,
            ),
            ProductModel(
                model_id="mb14-ultra",
                name="MateBook 14 酷睿 Ultra",
                short_name="MateBook 14 酷睿 Ultra",
                series="MateBook 14",
                os_family="windows",
                os_label="Windows 11",
                aliases=["MateBook 14 酷睿", "MateBook 14 Ultra", "MB14酷睿"],
                confusable_with=["mb14-hm"],
                has_public_price=False,
            ),
            ProductModel(
                model_id="d16",
                name="MateBook D 16（2024）",
                short_name="MateBook D 16",
                series="MateBook D",
                os_family="windows",
                os_label="Windows 11",
                aliases=["MateBook D 16", "D 16", "D16"],
                confusable_with=["d16se"],
                has_public_price=False,
            ),
            ProductModel(
                model_id="d16se",
                name="MateBook D 16 SE 版",
                short_name="MateBook D 16 SE",
                series="MateBook D",
                os_family="windows",
                os_label="Windows 11",
                aliases=["MateBook D 16 SE", "D 16 SE", "D16SE"],
                confusable_with=["d16"],
                has_public_price=False,
            ),
            ProductModel(
                model_id="pro-hm",
                name="HUAWEI MateBook Pro（鸿蒙版）",
                short_name="MateBook Pro 鸿蒙版",
                series="MateBook Pro",
                os_family="harmonyos",
                os_label="HarmonyOS 6.1",
                aliases=["MateBook Pro 鸿蒙版", "MateBook Pro HM", "Pro鸿蒙"],
                confusable_with=["pros-hm"],
                has_public_price=True,
            ),
            ProductModel(
                model_id="pros-hm",
                name="HUAWEI MateBook Pro S",
                short_name="MateBook Pro S",
                series="MateBook Pro",
                os_family="harmonyos",
                os_label="HarmonyOS 6.1",
                aliases=["MateBook Pro S", "Pro S"],
                confusable_with=["pro-hm"],
                has_public_price=True,
            ),
        ]
        
        self._facts = {
            "mb14-hm": [
                Fact(
                    id="mb14-hm:spec01:01",
                    model_id="mb14-hm",
                    kind="spec",
                    category="display",
                    text="屏幕尺寸：14.2 英寸",
                    tags=["display"],
                    source_title="MateBook 14 鸿蒙版规格",
                    source_path="fake/mb14-hm/specs.md",
                ),
                Fact(
                    id="mb14-hm:spec01:02",
                    model_id="mb14-hm",
                    kind="spec",
                    category="display",
                    text="分辨率：2880 × 1920",
                    tags=["display"],
                    source_title="MateBook 14 鸿蒙版规格",
                    source_path="fake/mb14-hm/specs.md",
                ),
                Fact(
                    id="mb14-hm:spec02:01",
                    model_id="mb14-hm",
                    kind="spec",
                    category="performance",
                    text="处理器：麒麟 X90",
                    tags=["performance"],
                    source_title="MateBook 14 鸿蒙版规格",
                    source_path="fake/mb14-hm/specs.md",
                ),
                Fact(
                    id="mb14-hm:spec03:01",
                    model_id="mb14-hm",
                    kind="spec",
                    category="portable",
                    text="重量：约 1.32 kg",
                    constraints=["典型值"],
                    tags=["portable"],
                    source_title="MateBook 14 鸿蒙版规格",
                    source_path="fake/mb14-hm/specs.md",
                ),
                Fact(
                    id="mb14-hm:card01:01",
                    model_id="mb14-hm",
                    kind="card",
                    category="display",
                    text="亮度：典型亮度 600 nits",
                    constraints=["典型亮度"],
                    tags=["display"],
                    source_title="MateBook 14 鸿蒙版屏幕卡",
                    source_path="fake/mb14-hm/display-card.md",
                ),
            ],
            "pro-hm": [
                Fact(
                    id="pro-hm:spec01:01",
                    model_id="pro-hm",
                    kind="spec",
                    category="display",
                    text="屏幕尺寸：14.2 英寸",
                    tags=["display"],
                    source_title="MateBook Pro 鸿蒙版规格",
                    source_path="fake/pro-hm/specs.md",
                ),
            ],
        }
        
        self._images = {
            "mb14-hm": [
                ImageAsset(
                    id="fake_mb14_appearance_01.jpg",
                    model_id="mb14-hm",
                    caption="MateBook 14 鸿蒙版外观",
                    tags=["appearance"],
                    width=1920,
                    height=1080,
                    kb_path="fake/mb14-hm/images/appearance_01.jpg",
                ),
            ],
        }
        
        self._prices = {
            "mb14-hm": [
                PriceRecord(
                    record_id="mb14-hm-01",
                    model_id="mb14-hm",
                    product_name="HUAWEI MateBook 14（鸿蒙版）",
                    spec="16GB+512GB",
                    price_type="官方商城页面价",
                    amount=6599.0,
                    verified_at="2026-10-17",
                    url="https://example.com/mb14",
                    status="已核验",
                ),
            ],
        }
    
    def status(self) -> KBStatus:
        return KBStatus(
            mode="local_mirror",
            kb_name="FakeKB",
            connected=True,
            detail="测试用虚构知识库",
            models=len(self._models),
            facts=sum(len(v) for v in self._facts.values()),
            images=sum(len(v) for v in self._images.values()),
            prices=sum(len(v) for v in self._prices.values()),
        )
    
    def models(self) -> list[ProductModel]:
        return self._models
    
    def get_model(self, model_id: str) -> Optional[ProductModel]:
        for m in self._models:
            if m.model_id == model_id:
                return m
        return None
    
    def find_models(self, text: str) -> list[tuple[ProductModel, float, str]]:
        """Alias match. Returns (model, score 0..1, matched_alias)."""
        results = []
        text_lower = text.lower()
        
        for m in self._models:
            # Check exact name
            if m.name.lower() == text_lower:
                results.append((m, 1.0, m.name))
                continue
            
            # Check series match (ambiguous if multiple models)
            if m.series.lower() in text_lower or text_lower in m.series.lower():
                # Check if confusable
                if m.confusable_with:
                    results.append((m, 0.5, m.series))
                else:
                    results.append((m, 0.8, m.series))
                continue
            
            # Check aliases
            for alias in m.aliases:
                if alias.lower() == text_lower:
                    results.append((m, 0.9, alias))
                    break
                elif alias.lower() in text_lower or text_lower in alias.lower():
                    results.append((m, 0.6, alias))
                    break
        
        # Sort by score desc
        results.sort(key=lambda x: x[1], reverse=True)
        return results
    
    def facts(self, model_id: str, kinds: Optional[list[str]] = None,
              categories: Optional[list[str]] = None,
              tags: Optional[list[str]] = None) -> list[Fact]:
        all_facts = self._facts.get(model_id, [])
        result = []
        for f in all_facts:
            if kinds and f.kind not in kinds:
                continue
            if categories and f.category not in categories:
                continue
            if tags and not any(t in f.tags for t in tags):
                continue
            result.append(f)
        return result
    
    def get_fact(self, fact_id: str) -> Optional[Fact]:
        for facts_list in self._facts.values():
            for f in facts_list:
                if f.id == fact_id:
                    return f
        return None
    
    def images(self, model_id: str, tags: Optional[list[str]] = None) -> list[ImageAsset]:
        all_images = self._images.get(model_id, [])
        if not tags:
            return all_images
        return [img for img in all_images if any(t in img.tags for t in tags)]
    
    def get_image(self, image_id: str) -> Optional[ImageAsset]:
        for images_list in self._images.values():
            for img in images_list:
                if img.id == image_id:
                    return img
        return None
    
    def image_bytes(self, image_id: str) -> tuple[bytes, str]:
        """Return fake 1x1 PNG."""
        # Minimal valid 1x1 PNG
        png_data = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\x00\x01\x00\x00'
            b'\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        return (png_data, "image/png")
    
    def prices(self, model_id: str) -> list[PriceRecord]:
        return self._prices.get(model_id, [])
    
    def search(self, query: str, model_id: Optional[str] = None, limit: int = 8) -> list[SearchHit]:
        """Simple mock search."""
        hits = []
        for m in self._models:
            if model_id and m.model_id != model_id:
                continue
            if query.lower() in m.name.lower():
                hits.append(SearchHit(
                    title=m.name,
                    path=f"fake/{m.model_id}/",
                    snippet=f"{m.name} {m.os_label}",
                    model_id=m.model_id,
                ))
        return hits[:limit]
    
    def drain_trace(self) -> list[TraceEntry]:
        return []
