from typing import Awaitable, Callable, Optional, override, ClassVar, Dict, Iterable, Literal, NewType, Protocol, Self, Type, Any, runtime_checkable
from functools import reduce
from abc import abstractclassmethod, abstractmethod
from dataclasses import MISSING, dataclass, asdict, fields, field

from cocotb.handle import SimHandleBase
from cocotb.triggers import Timer, _ParameterizedSingletonAndABC
from cocotb.utils import Decimal, ParametrizedSingleton
from cocotb import triggers
from cocotb import top
from cocotb import SIM_NAME
from cocotb.types.logic_array import LogicArray
from cocotb.types.range import Range
from cocotb.types import concat

# make pyright happy :D (top is only undefined during test discovery)
assert isinstance(top, SimHandleBase)

class CheckedLogicArray:
    def __init__(self, bits):
        self.bits = bits

    def __set_name__(self, owner, name):
        self._name = f'_{name}'

    def __get__(self, obj, owner=None) -> LogicArray:
        return getattr(obj, self._name)

    def __set__(self, obj, value):
        if isinstance(value, LogicArray):
            if value.range != Range(self.bits - 1, 'downto', 0):
                raise ValueError(f'LogicArray range must be {self.bits - 1} downto 0')
            new_value = value
        else:
            new_value = LogicArray(value, Range(self.bits - 1, 'downto', 0))

        setattr(obj, self._name, new_value)

@dataclass
class SVStruct():
    __quick_args: ClassVar[list[str]]

    @classmethod
    def __init_subclass__(cls, /, **kwargs) -> None:
        cls.__quick_args = kwargs.pop('quick_args', [])
        super().__init_subclass__(**kwargs)

        # We want all SVStructs to be dataclasses, but we provide __repr__():
        # We apply @dataclass(repr=False) manually
        cls = dataclass(repr=False)(cls)

    @staticmethod
    def __unflatten(flatkw: Dict[str, Any]) -> Dict[str, Dict | Any]:
        unflat_kw = dict[str, Dict | Any]()

        for k, v in flatkw.items():
            [*namespace_parts, true_k] = k.split('-')

            cursor = unflat_kw
            for namespace_part in namespace_parts:
                cursor = cursor.setdefault(namespace_part, dict[str, Dict | Any]())

            cursor[true_k] = v

        return unflat_kw

    @classmethod
    def from_flat(cls, **kwargs) -> Self:
        # Only unflatten if needed
        if next((x for x in kwargs.keys() if '-' in x), None):
            unflat_kw = cls.__unflatten(kwargs)
        else:
            unflat_kw = kwargs

        kw = dict()

        for field in fields(cls):
            assert isinstance(field.type, Type)
            field_name = field.name
            field_type = field.type

            if issubclass(field_type, SVStruct) and isinstance(unflat_kw[field_name], Dict):
                kw[field_name] = field_type.from_flat(**unflat_kw[field_name])
            else:
                kw[field_name] = unflat_kw[field_name]

        return cls(**kw)

    @classmethod
    def quick(cls, *args):
        return cls.from_flat(**{k: v for k, v in zip(cls.__quick_args, args)})

    @classmethod
    def bits(cls) -> int:
        bits = 0

        for field in fields(cls):
            assert isinstance(field.type, Type)
            field_name = field.name
            field_type = field.type

            if issubclass(field_type, SVStruct):
                bits += field_type.bits()
            elif issubclass(field_type, CheckedLogicArray):
                bits += cls.__dict__[field_name].bits
            else:
                raise TypeError(f'Unsupported type {field_type}')

        return bits

    @classmethod
    def from_signal(cls, signal):
        if SIM_NAME == 'Verilator' and isinstance(signal, SimHandleBase):
            raw = LogicArray(signal.value, Range(cls.bits() - 1, 'downto', 0))
            return cls.from_logicarray(raw)

        kw = dict()

        for field in fields(cls):
            assert isinstance(field.type, Type)
            field_name = field.name
            field_type = field.type

            if issubclass(field_type, SVStruct):
               kw[field_name] = field_type.from_signal(getattr(signal, field_name))
            elif issubclass(field_type, CheckedLogicArray):
                kw[field_name] = getattr(signal, field_name).value
            else:
                kw[field_name] = field_type(getattr(signal, field_name).value)

        return cls(**kw)

    @classmethod
    def from_array_signal_single(cls, signal, index) -> Self:
        if SIM_NAME != 'Verilator':
            return cls.from_signal(signal[index])

        element_bits = cls.bits()
        total_bits = signal.value.n_bits
        array_length = total_bits // element_bits

        r_index = array_length - index - 1
        lsb = element_bits * r_index
        msb = lsb + element_bits - 1

        raw = LogicArray(signal.value[lsb:msb], Range(cls.bits() - 1, 'downto', 0))
        return cls.from_logicarray(raw)

    @classmethod
    def from_array_signal(cls, signal) -> Iterable[Self]:
        if SIM_NAME == 'Verilator':
            element_bits = cls.bits()
            total_bits = signal.value.n_bits
            array_length = total_bits // element_bits
        else:
            array_length = len(signal)

        for i in range(array_length):
            yield cls.from_array_signal_single(signal, i)

    @classmethod
    def from_logicarray(cls, raw: LogicArray):
        kw = dict()
        offset = 0

        for field in reversed(fields(cls)):
            assert isinstance(field.type, Type)
            field_name = field.name
            field_type = field.type

            if issubclass(field_type, SVStruct):
                field_bits = field_type.bits()
                field_raw = LogicArray(raw[offset+field_bits-1:offset])

                kw[field_name] = field_type.from_logicarray(field_raw)
            elif issubclass(field_type, CheckedLogicArray):
                field_bits = cls.__dict__[field_name].bits
                field_raw = LogicArray(raw[offset+field_bits-1:offset])

                kw[field_name] = field_raw
            else:
                raise ValueError(f"Unsupported field type: {field_type}")

            offset += field_bits

        return cls(**kw)

    def write_to_signal(self, signal):
        if SIM_NAME == "Verilator" and isinstance(signal, SimHandleBase):
            signal.value = self.into_logicarray()
            return

        for field in fields(self):
            field_name = field.name

            if isinstance(getattr(self, field_name), SVStruct):
                getattr(self, field_name).write_to_signal(getattr(signal, field_name))
            else:
                getattr(signal, field_name).value = getattr(self, field_name)

    def into_logicarray(self) -> LogicArray:
        raw = list()

        for field in fields(self):
            field_name = field.name
            attr = getattr(self, field_name)

            if isinstance(attr, SVStruct):
                raw_attr = attr.into_logicarray()
            elif isinstance(attr, LogicArray):
                raw_attr = attr
            else:
                raw_attr = LogicArray(value=attr)

            raw.append(raw_attr)

        return reduce(concat, raw)

    def __repr__(self):
        ret = self.__class__.__name__ + '('
        field_count = len(fields(self))

        for idx, field in enumerate(fields(self)):
            field_name = field.name
            attr = getattr(self, field_name)

            ret += f'{field_name}='
            if isinstance(attr, LogicArray):
                if len(attr) == 1:
                    ret += 'T' if attr.integer == 1 else 'F'
                elif len(attr) < 8:
                    ret += repr(attr.integer)
                elif len(attr) % 4 == 0:
                    ret += f'{attr.integer:#0{len(attr)//4}x}';
                else:
                    ret += attr.binstr
            else:
                ret += repr(attr)

            if idx != field_count - 1:
                ret += ', '

        ret += ')'

        return ret

async def reset():
    top._log.info("Asserting reset signal")
    top.rst_n.value = 0
    await SimulationUpdate()
    top.rst_n.value = 1
    await SimulationUpdate()

async def flush():
    top._log.info("Asserting flush signal")
    top.flush.value = 1
    await RisingEdge()
    top.flush.value = 0
    await RisingEdge()

class AwaitableWrapper[T: Awaitable]:
    inner: T

    def __init__(self):
        self.inner = self.build_inner()

    def build_inner(self) -> T:
        raise NotImplementedError

    async def do_await(self):
        await self.inner

    def __await__(self):
        yield from self.do_await().__await__()

class RisingEdgesHoldingAssertion(AwaitableWrapper[triggers.RisingEdge]):
    count: int
    assertion: Callable[[], bool]
    message: Callable[[int], str]

    @override
    def __init__(self, count: int, assertion: Callable[[], bool], message: Optional[str]=None):
        self.count = count
        self.assertion = assertion

        details = f': {message}' if message else ''
        self.message = lambda n: f'Assertion violation in rising edge #{n}{details}'
        super().__init__()

    @override
    def build_inner(self) -> triggers.RisingEdge:
        return triggers.RisingEdge(top.clk)

    @override
    async def do_await(self):
        for i in range(self.count):
            await self.inner
            assert self.assertion(), self.message(i)

class RisingEdges(AwaitableWrapper[RisingEdgesHoldingAssertion]):
    count: int

    @override
    def __init__(self, count: int):
        self.count = count
        super().__init__()

    @override
    def build_inner(self) -> RisingEdgesHoldingAssertion:
        return RisingEdgesHoldingAssertion(self.count, lambda: True)

class RisingEdge(AwaitableWrapper[RisingEdges]):
    @override
    def build_inner(self) -> RisingEdges:
        return RisingEdges(1)

class SimulationUpdate(AwaitableWrapper[Timer]):
    @override
    def build_inner(self) -> Timer:
        return Timer(Decimal(1))
