#pragma once
#include "/cvmfs/sft.cern.ch/lcg/views/LCG_107/x86_64-el9-gcc11-opt/include/onnxruntime/onnxruntime_cxx_api.h"

#include <memory>
#include <vector>
#include <string>
#include <stdexcept>
#include <fstream>
#include <iostream>

namespace ff_interface {

class FFNetONNXRunner {
public:
    explicit FFNetONNXRunner(const std::string& model_path)
        : env_(ORT_LOGGING_LEVEL_WARNING, "FFNetInference"),
          session_opts_(),
          feature_count_(0) {

        std::ifstream f(model_path.c_str());
        if (!f.good()) throw std::runtime_error("Could not find ONNX model file: " + model_path);

        session_opts_.SetIntraOpNumThreads(1);
        session_ = std::make_unique<Ort::Session>(env_, model_path.c_str(), session_opts_);

        // Input shape to learn expected feature length (batch, F)
        Ort::AllocatorWithDefaultOptions alloc;
        auto type_info   = session_->GetInputTypeInfo(0);
        auto tensor_info = type_info.GetTensorTypeAndShapeInfo();
        auto shape       = tensor_info.GetShape();
        if (shape.size() != 2) {
            throw std::runtime_error("Model input is not rank-2 [batch, features].");
        }
        if (shape[1] <= 0) {
            throw std::runtime_error("Model feature dimension is dynamic/unknown. Export should fix it.");
        }
        feature_count_ = static_cast<size_t>(shape[1]);
        std::cout << "[FFNetONNXRunner] Loaded " << model_path
                  << " expecting feature_count=" << feature_count_ << std::endl;
    }

    // pass the raw vector in the exact feature_order 
    float compute_w_ff(const std::vector<float>& raw_input) const {
        if (raw_input.size() != feature_count_) {
            throw std::runtime_error(
                "[FFNetONNXRunner] raw_input.size()=" + std::to_string(raw_input.size()) +
                " does not match model feature_count=" + std::to_string(feature_count_) +
                ". Build the vector in the saved feature_order.json."
            );
        }
        Ort::MemoryInfo mem_info = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
        std::vector<int64_t> input_shape{1, static_cast<int64_t>(raw_input.size())};
        Ort::Value input_tensor = Ort::Value::CreateTensor<float>(
            mem_info,
            const_cast<float*>(raw_input.data()),
            raw_input.size(),
            input_shape.data(), input_shape.size()
        );

        const char* input_names[]  = {"raw_input"};
        const char* output_names[] = {"w_ff"};
        auto outputs = session_->Run(Ort::RunOptions{nullptr}, input_names, &input_tensor, 1, output_names, 1);
        return outputs[0].GetTensorData<float>()[0];
    }

    size_t feature_count() const { return feature_count_; }

private:
    Ort::Env env_;
    Ort::SessionOptions session_opts_;
    std::unique_ptr<Ort::Session> session_;
    size_t feature_count_;
};

inline std::unique_ptr<FFNetONNXRunner> g_ff_runner_instance;
inline void initialize_ff_runner(const std::string& model_path) {
    g_ff_runner_instance = std::make_unique<FFNetONNXRunner>(model_path);
}
inline FFNetONNXRunner& get_ff_runner() {
    if (!g_ff_runner_instance) throw std::runtime_error("FF runner not initialized.");
    return *g_ff_runner_instance;
}
inline void finalize_ff_runner() {
    g_ff_runner_instance.reset();  
  }
} // namespace ff_interface