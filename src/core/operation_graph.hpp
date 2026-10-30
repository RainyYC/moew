#pragma once
#include "../common.hpp"

// The shared ten-operation DAG. Keep edge emission order stable: adjacency
// order participates in deterministic ready and topological tie handling.
namespace operation_graph {
inline constexpr int kLayerStride = operation::kCount;

constexpr int node_id(int microbatch, int layer, int op, int layer_count) {
    return (microbatch * layer_count + layer) * operation::kCount + op;
}

constexpr int layer_of(int id, int layer_count) {
    return (id / operation::kCount) % layer_count;
}

constexpr int operation_of(int id) {
    return id % operation::kCount;
}

constexpr void decode_node(int id, int layer_count, int& microbatch, int& layer, int& op) {
    const int layer_stride = layer_count * operation::kCount;
    microbatch = id / layer_stride;
    const int in_microbatch = id % layer_stride;
    layer = in_microbatch / operation::kCount;
    op = in_microbatch % operation::kCount;
}

template <class Id, class Edge>
inline void append_layer_edges(int microbatch, int layer, int layer_count, Id id, Edge edge) {
    const int base = id(microbatch, layer, operation::kSharedForward);
    edge(base + operation::kDispatchForward, base + operation::kExpertForward);
    edge(base + operation::kExpertForward, base + operation::kCombineForward);
    edge(base + operation::kSharedForward, base + operation::kCombineForward);
    edge(base + operation::kCombineForward, base + operation::kSharedBackward);
    edge(base + operation::kCombineForward, base + operation::kCombineBackward);
    edge(base + operation::kCombineBackward, base + operation::kExpertInputGradient);
    edge(base + operation::kCombineBackward, base + operation::kExpertWeightGradient);
    edge(base + operation::kCombineBackward, base + operation::kSharedWeightGradient);
    edge(base + operation::kExpertInputGradient, base + operation::kDispatchBackward);
    edge(base + operation::kSharedBackward, base + operation::kDispatchBackward);
    if (layer > 0) {
        const int previous = id(microbatch, layer - 1, operation::kSharedForward);
        edge(previous + operation::kCombineForward, base + operation::kSharedForward);
        edge(previous + operation::kCombineForward, base + operation::kDispatchForward);
    }
    if (layer + 1 < layer_count) {
        const int next = id(microbatch, layer + 1, operation::kSharedForward);
        edge(next + operation::kDispatchBackward, base + operation::kSharedBackward);
        edge(next + operation::kDispatchBackward, base + operation::kCombineBackward);
    }
}
}  // namespace operation_graph
