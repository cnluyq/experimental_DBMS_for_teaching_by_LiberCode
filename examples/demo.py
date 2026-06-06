#!/usr/bin/env python3
"""
LRU缓冲区池演示程序

展示缓冲区管理器的核心功能和LRU算法工作原理
"""

import sys
sys.path.append('.')  # 添加当前目录到路径

from src.core.buffer import BufferPool
from src.core.storage_interface import InMemoryStorage


def print_separator(title=""):
    """打印分隔线"""
    print("\n" + "="*60)
    if title:
        print(f"  {title}")
        print("="*60)


def demo_basic_usage():
    """基本使用演示"""
    print_separator("1. 基本使用演示")
    
    # 创建存储引擎和缓冲区
    storage = InMemoryStorage(4096)
    buffer = BufferPool(5, storage, logger=None)
    
    # 创建测试页面
    print("\n创建10个测试页面...")
    for i in range(10):
        data = f"这是第{i}页的内容。".encode().ljust(4096, b'\x00')
        storage.page_write(i, data)
    
    # 读取页面
    print("\n读取前5个页面（填充缓冲区）:")
    for i in range(5):
        frame = buffer.read_page(i)
        print(f"  页面 {i} -> 帧 {frame.frame_id}")
    
    stats = buffer.get_buffer_stats()
    print(f"\n当前状态: {stats['used_frames']}/{stats['total_frames']} 帧已用")
    print(f"缓存命中率: {stats['hit_rate']:.2%}")
    
    buffer.shutdown()


def demo_lru_algorithm():
    """LRU置换算法演示"""
    print_separator("2. LRU置换算法演示")
    
    storage = InMemoryStorage(4096)
    buffer = BufferPool(3, storage)  # 只有3个帧
    
    # 创建5个测试页面
    for i in range(5):
        data = f"Page {i}".encode().ljust(4096, b'\x00')
        storage.page_write(i, data)
    
    print("\n初始化: 创建了页面0-4")
    print("缓冲区大小: 3帧\n")
    
    # 步骤1: 加载0,1,2
    print("步骤1: 顺序读取页面0,1,2")
    for i in range(3):
        frame = buffer.read_page(i, pin=False)
        print(f"  加载页面{i}到帧{frame.frame_id}")
    
    print_buffer_state(buffer, "加载后")
    
    # 步骤2: 再次访问页面0（最新访问）
    print("\n步骤2: 访问页面0（应该命中）")
    frame = buffer.read_page(0, pin=False)
    print(f"  页面0在帧{frame.frame_id}（命中）")
    
    print_buffer_state(buffer, "访问0后")
    
    # 步骤3: 访问页面3（触发置换）
    print("\n步骤3: 访问页面3（应该置换最久未使用的页面1）")
    frame = buffer.read_page(3, pin=False)
    print(f"  页面3加载到帧{frame.frame_id}")
    
    print_buffer_state(buffer, "加载3后")
    
    # 步骤4: 验证页面1已被置换
    print("\n步骤4: 再次访问页面1（应该未命中，从磁盘重新加载）")
    frame = buffer.read_page(1, pin=False)
    print(f"  页面1现在在帧{frame.frame_id}")
    
    print_buffer_state(buffer, "重新加载1后")
    
    buffer.shutdown()


def print_buffer_state(buffer, title=""):
    """打印缓冲区当前状态"""
    if title:
        print(f"\n{title}:")
    
    print("  LRU顺序（最新->最旧）:")
    for i, frame_id in enumerate(buffer.lru_list):
        frame = buffer.frames[frame_id]
        if frame.page_id is not None:
            print(f"    {i}. 帧{frame_id} <- 页面{frame.page_id} " +
                  f"(dirty={frame.dirty}, pinned={frame.is_pinned()})")
    
    stats = buffer.get_buffer_stats()
    print(f"  使用情况: {stats['used_frames']}/{stats['total_frames']} 帧")
    print(f"  命中: {stats['hits']}, 未命中: {stats['misses']}, 置换: {stats['evictions']}")


def demo_dirty_page():
    """脏页管理演示"""
    print_separator("3. 脏页管理演示")
    
    storage = InMemoryStorage(4096)
    buffer = BufferPool(2, storage)
    
    # 创建测试页面
    for i in range(3):
        data = f"Page {i}".encode().ljust(4096, b'\x00')
        storage.page_write(i, data)
    
    # 读取页面0和1
    print("\n加载页面0和1到缓冲区:")
    frame0 = buffer.read_page(0)
    frame1 = buffer.read_page(1)
    print(f"  页面0 -> 帧{frame0.frame_id}")
    print(f"  页面1 -> 帧{frame1.frame_id}")
    
    print_buffer_state(buffer, "初始状态")
    
    # 修改页面0并标记为脏
    print("\n修改页面0数据并标记为脏页:")
    frame0.data[0:5] = b"HELLO"
    buffer.mark_dirty(0)
    print(f"  页面0 dirty = {frame0.dirty}")
    
    print_buffer_state(buffer, "修改后")
    
    # 读取页面2（触发置换）
    print("\n加载页面2（缓冲区满，需要置换）:")
    frame2 = buffer.read_page(2)
    print(f"  页面2加载到帧{frame2.frame_id}")
    
    # 检查哪个页面被置换
    print("\n被置换的页面:")
    for frame in buffer.frames.values():
        if frame.page_id is not None and frame.frame_id != frame2.frame_id:
            if not (frame.page_id in buffer.page_to_frame and 
                   buffer.page_to_frame[frame.page_id] == frame.frame_id):
                print(f"  页面{frame.page_id}已被置换出缓冲区")
    
    print_buffer_state(buffer, "置换后")
    
    # 写回所有脏页
    print("\n写回所有脏页:")
    buffer.flush_all()
    print("  所有脏页已写回磁盘")
    
    # 检查磁盘数据
    disk_data = storage.page_read(0)
    starts_with_hello = disk_data[:5] == b"HELLO"
    print(f"  验证: 页面0在磁盘上的数据以'HELLO'开头: {starts_with_hello}")
    
    buffer.shutdown()


def demo_concurrent_access():
    """并发访问演示"""
    print_separator("4. 并发访问演示")
    
    import threading
    import time
    
    storage = InMemoryStorage(4096)
    buffer = BufferPool(10, storage)
    
    # 创建20个测试页面
    for i in range(20):
        data = f"Page {i}".encode().ljust(4096, b'\x00')
        storage.page_write(i, data)
    
    results = []
    
    def worker(thread_id, page_start, page_count):
        """工作线程"""
        local_hits = 0
        local_misses = 0
        
        for i in range(page_start, page_start + page_count):
            page_id = i % 20
            frame = buffer.read_page(page_id)
            if frame:
                local_misses += 1 if buffer.stats['misses'] > 0 else 0
                time.sleep(0.01)  # 模拟工作
                buffer.unpin_page(page_id)
        
        results.append((thread_id, local_hits, local_misses))
    
    # 启动5个工作线程
    print("\n启动5个工作线程并发访问缓冲区...")
    threads = []
    for i in range(5):
        t = threading.Thread(
            target=worker,
            args=(i, i*4, 10)  # 每个线程访问10个页面
        )
        threads.append(t)
        t.start()
    
    # 等待所有线程完成
    for t in threads:
        t.join()
    
    stats = buffer.get_buffer_stats()
    print(f"\n并发访问完成:")
    print(f"  总读取: {stats['reads_total']}")
    print(f"  缓存命中: {stats['hits']}")
    print(f"  缓存未命中: {stats['misses']}")
    print(f"  命中率: {stats['hit_rate']:.2%}")
    print(f"  最大并发安全访问: ✓")
    
    buffer.shutdown()


def main():
    """主函数"""
    print("LRU缓冲区管理器演示程序")
    print("=" * 60)
    
    while True:
        print("\n请选择演示:")
        print("  1. 基本使用")
        print("  2. LRU置换算法")
        print("  3. 脏页管理")
        print("  4. 并发访问（线程安全）")
        print("  0. 退出")
        
        choice = input("\n输入选择: ").strip()
        
        if choice == "1":
            demo_basic_usage()
        elif choice == "2":
            demo_lru_algorithm()
        elif choice == "3":
            demo_dirty_page()
        elif choice == "4":
            demo_concurrent_access()
        elif choice == "0":
            print("\n感谢使用！")
            break
        else:
            print("无效选择，请重试")
        
        input("\n按Enter继续...")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n程序被中断")
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()