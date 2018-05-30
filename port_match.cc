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

#include "port_match.h"

#include "../utils/ether.h"
#include "../utils/ip.h"
#include "../utils/tcp.h"

// TODO: Fix add command
// TODO: Add stuff to module_msg.proto

static inline int is_valid_gate(gate_idx_t gate) {
  return (gate < MAX_GATES || gate == DROP_GATE);
}

const Commands PortMatch::cmds = {
    {"add", "PortMatchCommandAddArg", MODULE_CMD_FUNC(&PortMatch::CommandAdd),
     Command::THREAD_UNSAFE},
    {"clear", "EmptyArg", MODULE_CMD_FUNC(&PortMatch::CommandClear),
     Command::THREAD_UNSAFE},
    {"set_default_gate", "PortMatchCommandSetDefaultGateArg",
     MODULE_CMD_FUNC(&PortMatch::CommandSetDefaultGate), Command::THREAD_SAFE}};

CommandResponse PortMatch::Init(const bess::pb::PortMatchArg &arg[[maybe_unused]]) {  
    default_gate_ = DROP_GATE;
  
  return CommandSuccess();
}

CommandResponse PortMatch::CommandAdd(const bess::pb::PortMatchCommandAddArg &arg) {
  
  gate_idx_t gate = arg.gate();
  if (!is_valid_gate(gate)) {
    return CommandFailure(EINVAL, "Invalid gate: %hu", gate);
  }

  be16_t dst_port = be16_t(static_cast<uint16_t>(arg.dst_port()));
  table_.Insert(dst_port, gate);
  
  return CommandSuccess();
}

CommandResponse PortMatch::CommandClear(const bess::pb::EmptyArg &) {
  table_.Clear();
  return CommandSuccess();
}

void PortMatch::ProcessBatch(Context *ctx, bess::PacketBatch *batch) {
  using bess::utils::Ethernet;
  using bess::utils::Ipv4;
  using bess::utils::Tcp;
  using bess::utils::be16_t;
  
  gate_idx_t default_gate;
  default_gate = ACCESS_ONCE(default_gate_);

  gate_idx_t out_gates[bess::PacketBatch::kMaxBurst];

  int cnt = batch->cnt();
  for (int i = 0; i < cnt; i++) {
    bess::Packet *pkt = batch->pkts()[i];

    Ethernet *eth = pkt->head_data<Ethernet *>();
    Ipv4 *ip = reinterpret_cast<Ipv4 *>(eth + 1);
    size_t ip_bytes = ip->header_length << 2;
    // will only match on TCP packets
    if (ip->protocol == Ipv4::Proto::kTcp) {
      Tcp *tcp =
        reinterpret_cast<Tcp *>(reinterpret_cast<uint8_t *>(ip) + ip_bytes);

      std::pair<be16_t, gate_idx_t> *result = table_.Find(be16_t(tcp->dst_port));
      if (result) {
        out_gates[i] = result->second;
      }
      else {
        out_gates[i] = default_gate;
      }
    }
    else {
      out_gates[i] = default_gate;
    }
    EmitPacket(ctx, pkt, out_gates[i]);
  }
    //RunSplit(out_gates, batch);
}

CommandResponse PortMatch::CommandSetDefaultGate(
    const bess::pb::PortMatchCommandSetDefaultGateArg &arg) {
  default_gate_ = arg.gate();
  return CommandSuccess();
}


ADD_MODULE(PortMatch, "port_match", "Classifier for packet dst port")
