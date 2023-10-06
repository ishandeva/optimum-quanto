import os
from tempfile import TemporaryDirectory

import pytest
import torch
from helpers import q_assert_close, random_qtensor, random_tensor

from quanto.quantization import QTensor


@pytest.mark.parametrize("input_shape", [(10,), (1, 10), (10, 32, 32)])
@pytest.mark.parametrize("int_dtype", [torch.int8, torch.int16], ids=["int8", "int16"])
def test_quantize_dequantize(input_shape, int_dtype, device):
    a = random_tensor(input_shape, dtype=torch.float32).to(device)
    qa = QTensor.quantize(a, int_dtype)
    q_assert_close(a, qa)


@pytest.mark.parametrize("input_shape", [(10,), (1, 10), (10, 32, 32)])
@pytest.mark.parametrize("int_dtype", [torch.int8, torch.int16, torch.int32], ids=["int8", "int16", "int32"])
def test_instantiate(input_shape, int_dtype, device):
    max_value = min(1024, torch.iinfo(int_dtype).max)
    data = torch.randint(-max_value, max_value, input_shape, dtype=int_dtype)
    qa = QTensor(data, scale=torch.tensor(1.0 / max_value)).to(device)
    assert torch.max(torch.abs(qa.dequantize())) <= 1


@pytest.mark.parametrize("input_shape", [(10,), (1, 10), (10, 32, 32)])
def test_rescale_int16_int8(input_shape, device):
    a = random_tensor((10,), dtype=torch.float32).to(device)
    qa = QTensor.quantize(a, int_dtype=torch.int16)
    # Rescale to int8
    qa_rescaled = qa.rescale(torch.int8)
    q_assert_close(a, qa_rescaled)


@pytest.mark.parametrize("input_shape", [(10,), (1, 10), (10, 32, 32)])
def test_rescale_int32_int8(input_shape, device):
    # We need to generate a quantized tensor manually to avoid large int32 data
    int_max_value = 1000
    data = torch.randint(-int_max_value, int_max_value, input_shape, dtype=torch.int32)
    scale = torch.tensor(1.0 / int_max_value)
    qa = QTensor(data, scale).to(device)
    # Get the actual maximum
    a = qa.dequantize()
    float_max_value = torch.max(torch.abs(a))
    assert float_max_value <= 1
    # Rescale to int8
    qa_rescaled = qa.rescale(torch.int8, float_max_value / torch.iinfo(torch.int8).max)
    # Since we chose the optimal scale, we must have used the whole integer range
    assert torch.max(torch.abs(qa_rescaled._data)) == torch.iinfo(torch.int8).max
    q_assert_close(a, qa_rescaled)


def test_quantized_tensor_serialization():
    qinputs = random_qtensor((1, 10, 32), dtype=torch.float32)
    with TemporaryDirectory() as tmpdir:
        qinputs_file = os.path.join(tmpdir, "qinputs.pt")
        torch.save(qinputs, qinputs_file)
        qinputs_reloaded = torch.load(qinputs_file)
    assert torch.equal(qinputs._data, qinputs_reloaded._data)
    assert torch.equal(qinputs._scale, qinputs_reloaded._scale)


def test_quantized_tensor_requires_grad(device):
    weight = random_tensor((10,), dtype=torch.float32).to(device)
    weight.requires_grad = True
    qweight = QTensor.quantize(weight)
    assert qweight.requires_grad is True


def test_quantized_tensor_backward(device):
    weight = random_tensor((10,), dtype=torch.float32).to(device)
    weight.requires_grad = True
    qweight = QTensor.quantize(weight)
    gradient = torch.randn((10,)).to(device)
    # Backpropagate gradient to the inner float weights
    qweight.dequantize().backward(gradient)
    assert torch.equal(weight.grad, gradient)


def test_quantized_tensor_chained_backward(device):
    a = random_tensor((10,), dtype=torch.float32).to(device)
    a.requires_grad = True
    qa = QTensor.quantize(a)
    b = random_tensor((10,), dtype=torch.float32).to(device)
    b.requires_grad = True
    qb = QTensor.quantize(b)
    # Evaluate the product
    prod = qa * qb
    # Backpropagate
    gradient = torch.randn((10,)).to(device)
    prod.backward(gradient)
    assert torch.allclose(a.grad, qb.dequantize() * gradient)
    assert torch.allclose(b.grad, qa.dequantize() * gradient)


def test_rescale_backward(device):
    a = random_tensor((10,), dtype=torch.float32).to(device)
    a.requires_grad = True
    qa = QTensor.quantize(a, int_dtype=torch.int16)
    # Rescale to int8
    qa_rescaled = qa.rescale(torch.int8)
    assert qa_rescaled.requires_grad is True
    # Backpropagate
    gradient = torch.randn((10,)).to(device)
    qa_rescaled.backward(gradient)
    assert torch.allclose(a.grad, gradient)