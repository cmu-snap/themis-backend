// Copyright (c) 2014-2016, The Regents of the University of California.
// Copyright (c) 2016-2017, Nefeli Networks, Inc.
// All rights reserved.
//
// Redistribution and use in source and binary forms, with or without
// modification, are permitted provided that the following conditions are met:
//
// * Redistributions of source code must retain the above copyright notice, this
// list of conditions and the following disclaimer.
//
// * Redistributions in binary form must reproduce the above copyright notice,
// this list of conditions and the following disclaimer in the documentation
// and/or other materials provided with the distribution.
//
// * Neither the names of the copyright holders nor the names of their
// contributors may be used to endorse or promote products derived from this
// software without specific prior written permission.
//
// THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
// AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
// IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
// ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
// LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
// CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
// SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
// INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
// CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
// ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
// POSSIBILITY OF SUCH DAMAGE.

#include "queue.h"

#include "../mem_alloc.h"
#include "../utils/format.h"

/* RAY */

#include "../utils/ip.h"
#include "../utils/ether.h"
#include "../utils/tcp.h"

using bess::utils::Ethernet;
using bess::utils::Ipv4;
using bess::utils::Tcp;

#define DEFAULT_QUEUE_SIZE 1024

const Commands Queue::cmds = {
    {"set_burst", "QueueCommandSetBurstArg",
     MODULE_CMD_FUNC(&Queue::CommandSetBurst), Command::THREAD_SAFE},
    {"set_size", "QueueCommandSetSizeArg",
     MODULE_CMD_FUNC(&Queue::CommandSetSize), Command::THREAD_UNSAFE},
    {"get_status", "QueueCommandGetStatusArg",
     MODULE_CMD_FUNC(&Queue::CommandGetStatus), Command::THREAD_SAFE}};

int Queue::Resize(int slots) {
  struct llring *old_queue = queue_;
  struct llring *new_queue;

  int bytes = llring_bytes_with_slots(slots);

  int ret;

  new_queue = static_cast<llring *>(mem_alloc_ex(bytes, alignof(llring), 0));
  if (!new_queue) {
    return -ENOMEM;
  }

  ret = llring_init(new_queue, slots, 0, 1);
  if (ret) {
    mem_free(new_queue);
    return -EINVAL;
  }

  /* migrate packets from the old queue */
  if (old_queue) {
    bess::Packet *pkt;

    while (llring_sc_dequeue(old_queue, (void **)&pkt) == 0) {
      ret = llring_sp_enqueue(new_queue, pkt);
      if (ret == -LLRING_ERR_NOBUF) {
        bess::Packet::Free(pkt);
      }
    }

    mem_free(old_queue);
  }

  queue_ = new_queue;

  if (backpressure_) {
    AdjustWaterLevels();
  }

  return 0;
}

CommandResponse Queue::Init(const bess::pb::QueueArg &arg) {
  task_id_t tid;
  CommandResponse err;

  tid = RegisterTask(nullptr);
  if (tid == INVALID_TASK_ID) {
    return CommandFailure(ENOMEM, "Task creation failed");
  }

  burst_ = bess::PacketBatch::kMaxBurst;

  if (arg.backpressure()) {
    VLOG(1) << "Backpressure enabled for " << name() << "::Queue";
    backpressure_ = true;
  }

  if (arg.size() != 0) {
    err = SetSize(arg.size());
    if (err.error().code() != 0) {
      return err;
    }
  } else {
    size_ = DEFAULT_QUEUE_SIZE;
    int ret = Resize(DEFAULT_QUEUE_SIZE);
    if (ret) {
      return CommandFailure(-ret);
    }
  }

  if (arg.prefetch()) {
    prefetch_ = true;
  }
 
  // ADDED BY RAY -- start dump with blank line
  dump_ << std::endl;
  flow_stats_ = {};
  
  return CommandSuccess();
}

void Queue::DeInit() {
  // ADDED BY RAY
  std::cout << dump_.str();
  
  bess::Packet *pkt;

  if (queue_) {
    while (llring_sc_dequeue(queue_, (void **)&pkt) == 0) {
      bess::Packet::Free(pkt);
    }
    mem_free(queue_);
  }
  
}

std::string Queue::GetDesc() const {
  const struct llring *ring = queue_;

  return bess::utils::Format("%u/%u", llring_count(ring), ring->common.slots);
}

/* from upstream */
void Queue::ProcessBatch(bess::PacketBatch *batch) {
  int queued =
      llring_mp_enqueue_burst(queue_, (void **)batch->pkts(), batch->cnt());
  if (backpressure_ && llring_count(queue_) > high_water_) {
    printf("QUEUE DETECTED BACKPRESSURE");
    SignalOverload();
  }

  stats_.enqueued += queued;

  int to_drop = 0;
  //int pkt_dropped = 0;

  if (queued < batch->cnt()) {
    to_drop = batch->cnt() - queued;
  }
  
  for (int i = 0; i < batch->cnt(); i++) {
    bess::Packet *pkt = batch->pkts()[i];
    Ethernet *eth = pkt->head_data<Ethernet *>();
    Ipv4 *ip = reinterpret_cast<Ipv4 *>(eth + 1);
    
    // don't do anything if this isn't a TCP packet
    if (ip->protocol == Ipv4::Proto::kTcp) {
      int ip_bytes = ip->header_length << 2;
      Tcp *tcp = reinterpret_cast<Tcp *>(reinterpret_cast<uint8_t *>(ip) + ip_bytes);
      uint32_t datalen = ip->length.value() - (tcp->offset * 4) - (ip->header_length * 4);
      
      num_pkts_ = num_pkts_ + 1;
      
      // output flow stats src port, seq num, datalen, queue size, dropped, queued, batch size
      if ( i < to_drop ) {   // packet is dropped
	//if (! (dump_ << tcp->src_port << "," << tcp->seq_num << "," << datalen << "," << llring_count(queue_) << ",1," << queued << "," << batch->cnt() << std::endl) ) {
	//if (! (dump_ << tcp->src_port << "," << tcp->seq_num << "," << datalen << "," << llring_count(queue_) << ",1," << queued << "," << batch->cnt() << std::endl) ) {
	//  printf("FAILED TO WRITE SOME VALUES!");
	//}
	dump_ << tcp->src_port << "," << tcp->seq_num << "," << datalen << "," << llring_count(queue_) << ",1," << queued << "," << batch->cnt();
	for( const auto& n : flow_stats_ ) {
	  dump_ << ",{'" << n.first << "':'" << n.second << "'}";
	}
	dump_ << std::endl;
      }
      else {  // packet isn't dropped
	// update per flow stats
	flow_stats_[tcp->src_port]++;
	dump_ << tcp->src_port << "," << tcp->seq_num << "," << datalen << "," << llring_count(queue_) << ",1," << queued << "," << batch->cnt();
	for( const auto& n : flow_stats_ ) {
	  dump_ << ",{'" << n.first << "':'" << n.second << "'}";
	}
	dump_ << std::endl;
	  
	// print out dump when you see FIN packet that's not dropped
	if (num_pkts_ < 256) {
	  if (datalen == 0) {
	    if (tcp->flags & Tcp::Flag::kFin) {
	      num_pkts_ = 0;
	      std::cout << dump_.str();
	      dump_.str("");
	      dump_.clear();
	      dump_ << std::endl;
	    }
	  }
	}
	else { // output dump and clear
	  num_pkts_ = 0;
	  std::cout << dump_.str();
	  dump_.str("");
	  dump_.clear();
	  dump_ << std::endl;
	}
      }	
    }
  }
  
    if (queued < batch->cnt()) {
      to_drop = batch->cnt() - queued;
      stats_.dropped += to_drop;    
      bess::Packet::Free(batch->pkts() + queued, to_drop);
    }

  
  /* RAY - Record sequence number of incoming packet and size of queue 
  // assume batch size of 1
  if (queued < batch->cnt()) {
    int to_drop = batch->cnt() - queued;
    stats_.dropped += to_drop;

    int cnt = batch->cnt();

    for (int i = 0; i < cnt; i++) {  // possible there is more than one packet in batch
      bess::Packet *pkt = batch->pkts()[i];
      Ethernet *eth = pkt->head_data<Ethernet *>();
      Ipv4 *ip = reinterpret_cast<Ipv4 *>(eth + 1);

      // don't do anything if this isn't a TCP packet
      if (ip->protocol == Ipv4::Proto::kTcp) {
	int ip_bytes = ip->header_length << 2;
	Tcp *tcp = reinterpret_cast<Tcp *>(reinterpret_cast<uint8_t *>(ip) + ip_bytes);
	uint32_t datalen = ip->length.value() - (tcp->offset * 4) - (ip->header_length * 4);
	// actually should only print 1 if this cnt is  within number of pkts that was queued
	if (! (dump_ << tcp->src_port << "," << tcp->seq_num << "," << datalen << "," << llring_count(queue_) << ",1," << queued << "," << batch->cnt() << std::endl) ) {
	  printf("FAILED TO WRITE SOME VALUES!");
	}
     
	num_pkts_ = num_pkts_ + 1;
      }
    }
    bess::Packet::Free(batch->pkts() + queued, to_drop);
  }
  
  else { // packet wasn't dropped
    int cnt = batch->cnt();

    for (int i = 0; i < cnt; i++) {  // possible there is more than one packet in batch
      bess::Packet *pkt = batch->pkts()[i];
      Ethernet *eth = pkt->head_data<Ethernet *>();
      Ipv4 *ip = reinterpret_cast<Ipv4 *>(eth + 1);
    
      // don't do anything if this isn't a TCP packet
      if (ip->protocol == Ipv4::Proto::kTcp) {
	int ip_bytes = ip->header_length << 2;
	Tcp *tcp = reinterpret_cast<Tcp *>(reinterpret_cast<uint8_t *>(ip) + ip_bytes);
	uint32_t datalen = ip->length.value() - (tcp->offset * 4) - (ip->header_length * 4);
	if (! (dump_ << tcp->src_port << "," << tcp->seq_num << "," << datalen << "," << llring_count(queue_) << ",0," << queued << "," << batch->cnt() << std::endl)) {
	  printf("FAILED TO WRITE SOME VALUES!");
	}
	num_pkts_ = num_pkts_ + 1;
      
	// print out dump when you see FIN packet that's not dropped
	if (num_pkts_ < 256) {
	  if (datalen == 0) {
	    if (tcp->flags & Tcp::Flag::kFin) {
	      num_pkts_ = 0;
	      std::cout << dump_.str();
	      dump_.str("");
	      dump_.clear();
	      dump_ << std::endl;
	    }
	  }
	}
	else { // output dump and clear
	  num_pkts_ = 0;
	  std::cout << dump_.str();
	  dump_.str("");
	  dump_.clear();
	  dump_ << std::endl;
	}
      }
    }
  }
  */
}

/* to downstream */
struct task_result Queue::RunTask(void *) {
  if (children_overload_ > 0) {
    printf("QUEUE DETECTED OVERLOAD");
    return {
        .block = true, .packets = 0, .bits = 0,
    };
  }

  bess::PacketBatch batch;

  const int burst = ACCESS_ONCE(burst_);
  const int pkt_overhead = 24;

  uint64_t total_bytes = 0;

  uint32_t cnt = llring_sc_dequeue_burst(queue_, (void **)batch.pkts(), burst);

  if (cnt == 0) {
    return {.block = true, .packets = 0, .bits = 0};
  }  
  
  stats_.dequeued += cnt;
  batch.set_cnt(cnt);

  // update flow stats for each dequeued packet
  for (int i = 0; i < batch.cnt(); i++) {
    bess::Packet *pkt = batch.pkts()[i];
    Ethernet *eth = pkt->head_data<Ethernet *>();
    Ipv4 *ip = reinterpret_cast<Ipv4 *>(eth + 1);
    
    // don't do anything if this isn't a TCP packet
    if (ip->protocol == Ipv4::Proto::kTcp) {
      int ip_bytes = ip->header_length << 2;
      Tcp *tcp = reinterpret_cast<Tcp *>(reinterpret_cast<uint8_t *>(ip) + ip_bytes);
      flow_stats_[tcp->src_port]--;
    }
  }
  
  if (prefetch_) {
    for (uint32_t i = 0; i < cnt; i++) {
      total_bytes += batch.pkts()[i]->total_len();
      rte_prefetch0(batch.pkts()[i]->head_data());
    }
  } else {
    for (uint32_t i = 0; i < cnt; i++) {
      total_bytes += batch.pkts()[i]->total_len();
    }
  }

  RunNextModule(&batch);

  if (backpressure_ && llring_count(queue_) < low_water_) {
    SignalUnderload();
  }

  return {.block = false,
          .packets = cnt,
          .bits = (total_bytes + cnt * pkt_overhead) * 8};
}

CommandResponse Queue::CommandSetBurst(
    const bess::pb::QueueCommandSetBurstArg &arg) {
  uint64_t burst = arg.burst();

  if (burst > bess::PacketBatch::kMaxBurst) {
    return CommandFailure(EINVAL, "burst size must be [0,%zu]",
                          bess::PacketBatch::kMaxBurst);
  }

  burst_ = burst;
  return CommandSuccess();
}

CommandResponse Queue::SetSize(uint64_t size) {
  if (size < 4 || size > 16384) {
    return CommandFailure(EINVAL, "must be in [4, 16384]");
  }

  if (size & (size - 1)) {
    return CommandFailure(EINVAL, "must be a power of 2");
  }

  int ret = Resize(size);
  if (ret) {
    return CommandFailure(-ret);
  }
  size_ = size;

  return CommandSuccess();
}

CommandResponse Queue::CommandSetSize(
    const bess::pb::QueueCommandSetSizeArg &arg) {
  return SetSize(arg.size());
}

CommandResponse Queue::CommandGetStatus(
    const bess::pb::QueueCommandGetStatusArg &) {
  bess::pb::QueueCommandGetStatusResponse resp;
  resp.set_count(llring_count(queue_));
  resp.set_size(size_);
  resp.set_enqueued(stats_.enqueued);
  resp.set_dequeued(stats_.dequeued);
  resp.set_dropped(stats_.dropped);
  return CommandSuccess(resp);
}

void Queue::AdjustWaterLevels() {
  high_water_ = static_cast<uint64_t>(size_ * kHighWaterRatio);
  low_water_ = static_cast<uint64_t>(size_ * kLowWaterRatio);
}

CheckConstraintResult Queue::CheckModuleConstraints() const {
  CheckConstraintResult status = CHECK_OK;
  if (num_active_tasks() - tasks().size() < 1) {  // Assume multi-producer.
    LOG(ERROR) << "Queue has no producers";
    status = CHECK_NONFATAL_ERROR;
  }

  if (tasks().size() > 1) {  // Assume single consumer.
    LOG(ERROR) << "More than one consumer for the queue" << name();
    return CHECK_FATAL_ERROR;
  }

  return status;
}

ADD_MODULE(Queue, "queue",
           "terminates current task and enqueue packets for new task")
