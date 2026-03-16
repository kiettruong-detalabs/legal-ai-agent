#!/usr/bin/env python3
"""Test diacritics fallback search"""
import sys
sys.path.insert(0, '/home/admin_1/projects/legal-ai-agent/src')

from api.main import multi_query_search, restore_diacritics, has_vietnamese_diacritics

print("=" * 60)
print("Testing Vietnamese Diacritics Restoration")
print("=" * 60)

# Test diacritics detection
test_queries = [
    "thoi gian thu viec toi da",
    "nghi phep nam bao nhieu ngay", 
    "thue suat thue tndn",
    "thời gian thử việc tối đa"  # Already has diacritics
]

print("\n1. Testing diacritics detection:")
for q in test_queries:
    has_diacritics = has_vietnamese_diacritics(q)
    restored = restore_diacritics(q)
    print(f"  '{q}'")
    print(f"    → Has diacritics: {has_diacritics}")
    print(f"    → Restored: '{restored}'")
    print()

# Test search
print("\n2. Testing search results:")
print("-" * 60)

test_cases = [
    ("thoi gian thu viec toi da", "Should find BLLĐ Điều 25"),
    ("nghi phep nam bao nhieu ngay", "Should find BLLĐ Điều 113"),
    ("thue suat thue tndn", "Should find Luật Thuế TNDN")
]

for query, expected in test_cases:
    print(f"\nQuery: '{query}'")
    print(f"Expected: {expected}")
    
    results = multi_query_search(query, domains=None, limit=5)
    
    if results:
        print(f"✓ Found {len(results)} results:")
        for i, r in enumerate(results[:3], 1):
            print(f"  {i}. {r['law_title']} - {r.get('article', 'N/A')}")
            print(f"     Rank: {r.get('rank', 0):.2f}")
            snippet = r['content'][:100].replace('\n', ' ')
            print(f"     Content: {snippet}...")
    else:
        print(f"✗ No results found!")
    print("-" * 60)

print("\n✓ Test completed!")
