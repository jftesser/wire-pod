#include "sdkMicQueue.h"
#include <cassert>
#include <iostream>
using Anki::Vector::MicData::SDKMicQueue;
int main() {
  SDKMicQueue queue;
  SDKMicQueue::Clock::time_point start{};
  std::array<int16_t, 160> pcm{};
  pcm[0] = -32768; pcm[159] = 32767;
  queue.Push(pcm.data(), pcm.size(), 10, start);
  assert(queue.Drain(start).empty()); // Opt-in only.
  queue.Renew(1, true, start);
  for (unsigned i = 0; i < 10; ++i) queue.Push(pcm.data(), pcm.size(), i*10, start);
  auto blocks = queue.Drain(start);
  assert(blocks.size() == 10);
  for (unsigned i = 0; i < blocks.size(); ++i) {
    assert(blocks[i].session == 1 && blocks[i].sequence == i && blocks[i].timestamp == i*10);
    assert(blocks[i].samples == pcm);
  }
  // Renewals keep source sequence uninterrupted; stop discards pending audio.
  queue.Renew(1, true, start + std::chrono::seconds(1));
  queue.Push(pcm.data(), pcm.size(), 100, start + std::chrono::seconds(2));
  assert(queue.Drain(start + std::chrono::seconds(2))[0].sequence == 10);
  queue.Push(pcm.data(), pcm.size(), 110, start + std::chrono::seconds(2));
  queue.Renew(1, false, start + std::chrono::seconds(2));
  assert(queue.Drain(start + std::chrono::seconds(2)).empty());
  // Expiration fails closed, even if a late heartbeat arrives.
  queue.Renew(2, true, start);
  queue.Push(pcm.data(), pcm.size(), 20, start);
  assert(queue.Drain(start + std::chrono::seconds(3)).empty());
  queue.Renew(2, true, start + std::chrono::seconds(4));
  queue.Push(pcm.data(), pcm.size(), 30, start + std::chrono::seconds(4));
  assert(queue.Drain(start + std::chrono::seconds(4)).empty());
  // Overflow does not grow memory or silently splice audio after a missing block.
  queue.Renew(3, true, start);
  for (unsigned i = 0; i <= SDKMicQueue::kMaxBlocks; ++i) queue.Push(pcm.data(), pcm.size(), i*10, start);
  assert(queue.Drain(start).empty());
  queue.Renew(3, true, start);
  queue.Push(pcm.data(), pcm.size(), 0, start);
  assert(queue.Drain(start).empty());
  // A fresh session recovers, starts at zero and carries no stale audio.
  queue.Renew(4, true, start);
  queue.Push(pcm.data(), pcm.size(), 0, start);
  auto fresh = queue.Drain(start);
  assert(fresh.size() == 1 && fresh[0].session == 4 && fresh[0].sequence == 0);
  queue.Push(pcm.data(), 159, 10, start);
  assert(queue.Drain(start).empty());
  // A late heartbeat cannot revive its expired session even before a drain occurs.
  queue.Renew(5, true, start);
  queue.Renew(5, true, start + std::chrono::seconds(4));
  queue.Push(pcm.data(), pcm.size(), 0, start + std::chrono::seconds(4));
  assert(queue.Drain(start + std::chrono::seconds(4)).empty());
  // A fresh owner can recover after an expired old lease without waiting for drain.
  queue.Renew(6, true, start);
  queue.Renew(7, true, start + std::chrono::seconds(4));
  queue.Push(pcm.data(), pcm.size(), 0, start + std::chrono::seconds(4));
  assert(queue.Drain(start + std::chrono::seconds(4)).size() == 1);
  std::cout << "SDK mic queue: opt-in, FIFO, renewal, stop, expiry, overflow, restart passed\n";
}
