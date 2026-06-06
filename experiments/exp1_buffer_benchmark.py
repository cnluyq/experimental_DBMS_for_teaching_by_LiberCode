#!/usr/bin/env python3
"""
实验1：缓冲区池性能分析
"""

import random
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.buffer import BufferPool
from src.core.storage_interface import InMemoryStorage

def test_lru_algorithm():
    """测试LRU基本行为"""
    print("="*60)
    print("任务1：LRU算法行为验证")
    print("="*60)

    storage = InMemoryStorage(page_size=4096)
    buffer = BufferPool(num_frames=3, storage_engine=storage)

    # 初始化10个页面
    for i in range(10):
        data = f"Page {i}".encode().ljust(4096, b'\x00')
        storage.page_write(i, data)

    print("步骤1: 顺序读入页面 0,1,2（应填满缓冲区）")
    for i in range(3):
        frame = buffer.read_page(i, pin=False)
        print(f"  读页面 {i} -> Frame {frame.frame_id}")
        if i == 2:
            print(f"  当前LRU顺序（头→尾）: {buffer.lru_list}")

    print("\n步骤2: 再次读页面0（应命中）")
    frame = buffer.read_page(0, pin=False)
    print(f"  读页面 0 -> Frame {frame.frame_id}")
    print(f"  LRU顺序更新: {buffer.lru_list}")

    print("\n步骤3: 读页面3（应置换最久未使用的页面1）")
    frame = buffer.read_page(3, pin=False)
    print(f"  读页面 3 -> Frame {frame.frame_id}")
    print(f"  LRU顺序: {buffer.lru_list}")

    # 验证页面1被置换
    frame1_info = buffer.get_frame_info(1)
    print(f"\n验证: 页面1的缓冲区信息: {frame1_info}")
    assert frame1_info is None, "页面1应该已被置换出缓冲区"

    print("\n✅ LRU行为验证通过！\n")
    buffer.shutdown()


def measure_hit_rate_workload(workload, num_frames):
    """测量给定工作负载下的命中率"""
    storage = InMemoryStorage(page_size=4096)
    buffer = BufferPool(num_frames=num_frames, storage_engine=storage)

    # 准备数据（假设50个不同页面）
    num_pages = 50
    for i in range(num_pages):
        data = f"Data-{i}".encode().ljust(4096, b'\x00')
        storage.page_write(i, data)

    # 执行工作负载
    for page_id in workload:
        buffer.read_page(page_id, pin=False)

    stats = buffer.get_buffer_stats()
    buffer.shutdown()
    return stats['hit_rate']


def test_different_workloads():
    """测试不同访问模式对命中率的影响"""
    print("="*60)
    print("任务2：不同工作负载的命中率分析（缓冲区=10帧）")
    print("="*60)

    random.seed(42)

    workloads = {
        "顺序访问": list(range(50)),  # 访问50个不同页面一次
        "循环顺序": [i % 10 for i in range(100)],  # 循环访问10个页面
        "热点访问": [0]*70 + [i for i in range(1, 31)],  # 70%访问页面0，30%其他
        "随机访问": [random.randint(0, 49) for _ in range(100)],  # 50页中随机
        "Zipf分布": generate_zipf_workload(100, theta=1.0, num_pages=50),
    }

    for name, wl in workloads.items():
        hit_rate = measure_hit_rate_workload(wl, num_frames=10)
        print(f"  {name:15s} 命中率: {hit_rate:6.2%}")

    print()


def test_buffer_size_impact():
    """测试缓冲区大小对命中率的影响"""
    print("="*60)
    print("任务3：缓冲区大小对命中率的影响（随机工作负载）")
    print("="*60)

    random.seed(42)
    workload = [random.randint(0, 49) for _ in range(1000)]

    print(f"工作负载: 1000次随机访问（50个不同页面）\n")

    for frames in [5, 10, 20, 50, 100]:
        hit_rate = measure_hit_rate_workload(workload, frames)
        print(f"  帧数={frames:3d} → 命中率: {hit_rate:6.2%}")

    print("\n📊 分析：随着缓冲区增大，命中率如何变化？")
    print("   在高冲突工作负载（50页1000次随机）下，需要多大缓存才能达到90%命中率？\n")


def generate_zipf_workload(n, theta=1.0, num_pages=50):
    """生成Zipf分布的工作负载"""
    # 简化版Zipf：第i个页面的概率正比于 1/(i+1)^theta
    ranks = range(1, num_pages + 1)
    weights = [1.0 / (r ** theta) for r in ranks]
    total = sum(weights)
    probabilities = [w / total for w in weights]

    workload = []
    for _ in range(n):
        # 轮盘赌选择
        r = random.random()
        cumsum = 0
        for page_id, p in enumerate(probabilities):
            cumsum += p
            if r < cumsum:
                workload.append(page_id)
                break
    return workload


def test_varying_reference_patterns():
    """测试局部性对命中率的影响"""
    print("="*60)
    print("任务4：访问局部性分析（固定10帧缓冲区）")
    print("="*60)

    random.seed(42)

    # 模式1：完全随机（无局部性）
    wl1 = [random.randint(0, 99) for _ in range(500)]

    # 模式2：高局部性（循环访问10个页面）
    wl2 = [i % 10 for i in range(500)]

    # 模式3：中等局部性（20页中循环）
    wl3 = [i % 20 for i in range(500)]

    hit1 = measure_hit_rate_workload(wl1, 10)
    hit2 = measure_hit_rate_workload(wl2, 10)
    hit3 = measure_hit_rate_workload(wl3, 10)

    print(f"  完全随机(100页)    : {hit1:6.2%}")
    print(f"  高局部性(10页循环) : {hit2:6.2%}")
    print(f"  中等局部性(20页循环): {hit3:6.2%}")

    print("\n💡 结论：程序的访问局部性对缓存命中率有巨大影响！")
    print("   工程优化方向：\n")
    print("   1. 数据结构设计提高局部性（如数组连续存储）")
    print("   2. 预取（Prefetching）：预测未来访问提前加载")
    print("   3. 缓存友好算法：减少跨页访问\n")


def experiment_different_algorithms():
    """（选做）实现其他置换算法并对比"""
    print("="*60)
    print("任务5：置换算法对比（LRU vs FIFO vs Clock）")
    print("="*60)
    print("⚠️  此任务需要先扩展BufferPool类，添加新算法\n")

    print("  [待实现] 请在BufferPool中添加以下算法：")
    print("    • FIFO：先进先出")
    print("    • Clock：时钟算法（二次机会）")
    print("\n  实现后，用相同工作负载测试，绘制对比图表。\n")


def main():
    print("\n" + "="*60)
    print(" 实验1：缓冲区池性能分析")
    print("="*60 + "\n")

    # 任务1：验证LRU行为
    test_lru_algorithm()

    # 任务2：不同工作负载
    test_different_workloads()

    # 任务3：缓冲区大小影响
    test_buffer_size_impact()

    # 任务4：访问局部性
    test_varying_reference_patterns()

    # 任务5：算法对比（选做）
    experiment_different_algorithms()

    print("="*60)
    print("实验完成！请整理数据并撰写实验报告。")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
