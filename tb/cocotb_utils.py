from contextlib import AbstractAsyncContextManager, contextmanager
from enum import Enum
import logging

from logging import Logger
from typing import AsyncGenerator, Awaitable, Callable, Mapping, Optional, override, ClassVar, Dict, Iterable, Self, Type, Any
from functools import reduce
from abc import ABC, abstractmethod
from dataclasses import dataclass, fields

import cocotb

from cocotb.handle import SimHandleBase
from cocotb.queue import Queue
from cocotb.task import Task
from cocotb.triggers import FallingEdge, Timer
from cocotb.utils import Decimal
from cocotb import triggers
from cocotb import top
from cocotb import SIM_NAME
from cocotb.types.logic_array import LogicArray
from cocotb.types.range import Range
from cocotb.types import concat
from cocotb.clock import Clock

# make pyright happy :D (top is only undefined during test discovery)
assert isinstance(top, SimHandleBase)

LOGGER = logging.getLogger('tb')
LOGGER.setLevel(logging.INFO)

type PseudoSignalMapping = Mapping[str, PseudoSignalMapping | str]

class PseudoSignal:
    _signal_mapping: 'Mapping[str, SimHandleBase | PseudoSignal]'
    
    def __init__(self, handle: SimHandleBase, signal_mapping: PseudoSignalMapping):
        self._signal_mapping = dict()
        for name, value in signal_mapping.items():
            if isinstance(value, str):
                self._signal_mapping[name] = getattr(handle, value)
            elif isinstance(value, Mapping):
                self._signal_mapping[name] = PseudoSignal(handle, value)

    def __getattr__(self, name: str) -> 'SimHandleBase | PseudoSignal':
        return self._signal_mapping[name]

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
    def zeroed(cls) -> Self:
        kw = dict()

        for field in fields(cls):
            assert isinstance(field.type, Type)
            field_name = field.name
            field_type = field.type

            if issubclass(field_type, SVStruct):
               kw[field_name] = field_type.zeroed()
            else:
                kw[field_name] = 0

        return cls(**kw)

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

@dataclass
class ValRdyInterface:
    val: SimHandleBase
    rdy: SimHandleBase
    data: SimHandleBase | PseudoSignal
    rdy_is_ack: bool = False
    producer_name: str = "DUT"
    consumer_name: str = "DUT"

class QueueState(Enum):
    EMPTY = 0,
    PARTIAL = 1,
    FULL = 2,

class TBTask(ABC):
    __task: Task
    __stop_event: Optional[triggers.Event]
    __subtasks: Iterable['TBTask']
    
    def __init__(self, *, use_kill: bool=False, subtasks: Iterable['TBTask']=[]):
        self.__task = cocotb.create_task(self._task_coroutine())
        self.__stop_event = None if use_kill else triggers.Event()
        self.__subtasks = subtasks
    
    @property
    def _stop_event(self) -> triggers.Event:
        if self.__stop_event is None:
            raise ValueError("There is no stop event, this task must be killed")
        return self.__stop_event
    
    @abstractmethod
    async def _task_coroutine(self):
        pass
    
    async def start(self):
        for task in self.__subtasks:
            await task.start()
            
        await cocotb.start(self.__task)

    async def stop(self):
        if self.__stop_event is None:
            self.__task.kill()
        else:
            self.__stop_event.set()
            await self.__task.join()
        
        for task in self.__subtasks:
            await task.stop()

class ValRdyMonitor[Data: SVStruct](TBTask):
    interface: ValRdyInterface
    bus_data_type: Type[Data]

    logger: Logger

    def __init__(self, interface: ValRdyInterface, bus_data_type: Type[Data]):
        super().__init__()
        
        self.interface = interface
        self.bus_data_type = bus_data_type

        self.logger = LOGGER.getChild(self.__class__.__name__)

    async def _task_coroutine(self):
        self.logger.info(f'Started monitoring the Valid-Ready interface between {self.interface.producer_name} and {self.interface.consumer_name}')

        next_iteration_trigger = triggers.First(triggers.RisingEdge(top.clk), self._stop_event.wait())

        while not self._stop_event.is_set():
            if self.interface.rdy.value == 1 and self.interface.val.value == 1:
                value = self.bus_data_type.from_signal(self.interface.data)
                self.logger.info(f"{self.interface.producer_name} -> {self.interface.consumer_name}: {value}")

            await next_iteration_trigger

        self.logger.info(f'Stopped monitoring the Valid-Ready interface between {self.interface.producer_name} and {self.interface.consumer_name}')

class ValRdyDriver[Data: SVStruct](TBTask):
    interface: ValRdyInterface
    bus_data_type: Type[Data]
    enabled: bool

    logger: Logger
    queue: Queue[Data]
    ready_event: triggers.Event

    def __init__(self, interface: ValRdyInterface, bus_data_type: Type[Data], enabled: bool=True):
        super().__init__(subtasks=[ValRdyMonitor(interface, bus_data_type)])
        
        self.interface = interface
        self.bus_data_type = bus_data_type
        self.enabled = enabled

        self.logger = LOGGER.getChild(self._get_name())
        self.queue = Queue()
        self.ready_event = triggers.Event()

    @property
    def queue_state(self):
        if self.queue.empty():
            return QueueState.EMPTY
        elif self.queue.full():
            return QueueState.FULL
        else:
            return QueueState.PARTIAL

    @contextmanager
    def disabled(self):
        old_enabled = self.enabled
        self.enabled = False
        try:
            yield
        finally:
            self.enabled = old_enabled

    async def _task_coroutine(self):
        self.logger.info(f'Started driving the Valid-Ready interface as a {self._driving_mode()}')

        next_iteration_trigger = triggers.First(triggers.RisingEdge(top.clk), self._stop_event.wait())

        await self._driver_setup()
        await SimulationUpdate()
        self.ready_event.set()
        
        while not self._stop_event.is_set():
            await self._driver_on_rising_edge()
            await next_iteration_trigger

        await self._driver_cleanup()

        self.logger.info(f'Stopped driving the Valid-Ready interface as a {self._driving_mode()}')

    @override
    async def start(self):
        await super().start()
        await self.ready_event.wait()

    @abstractmethod
    def _get_name(self):
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def _driving_mode() -> str:
        raise NotImplementedError

    @abstractmethod
    async def _driver_setup(self):
        raise NotImplementedError

    @abstractmethod
    async def _driver_on_rising_edge(self):
        raise NotImplementedError

    @abstractmethod
    async def _driver_cleanup(self):
        raise NotImplementedError

class ValRdyProducer[Data: SVStruct](ValRdyDriver[Data]):
    def _get_name(self):
        return self.interface.producer_name.replace(' ', '')

    @staticmethod
    def _driving_mode() -> str:
        return 'producer'
        
    @property
    @override
    def queue_state(self):
        # Take into account that the value in head could be latched
        if self.queue.empty() and self.interface.val.value == 0:
            return QueueState.EMPTY
        elif self.queue.full():
            return QueueState.FULL
        else:
            return QueueState.PARTIAL

    async def enqueue_values(self, *values: Data):
        for value in values:
            await self.queue.put(value)

    async def _driver_setup(self):
        self.interface.val.value = 0
        self.bus_data_type.zeroed().write_to_signal(self.interface.data)

    async def _driver_on_rising_edge(self):
        if self.interface.rdy.value == 1 and self.interface.val.value == 1:
            self.interface.val.value = 0
        
        await FallingEdge(top.clk)
        
        if self.interface.val.value == 0 and self.enabled and not self.queue.empty():
            self.interface.val.value = 1
            self.queue.get_nowait().write_to_signal(self.interface.data)

    async def _driver_cleanup(self):
        self.interface.val.setimmediatevalue(0)

class ValRdyConsumer[Data: SVStruct](ValRdyDriver[Data]):
    def _get_name(self):
        return self.interface.consumer_name.replace(' ', '')

    @staticmethod
    def _driving_mode() -> str:
        return 'consumer'

    async def dequeue_value(self) -> Data:
        return await self.queue.get()

    async def dequeue_values(self, n: int=-1) -> AsyncGenerator[Data]:
        count = 0

        while count != n:
            next = await self.dequeue_value()
            count += 1
            yield next

    async def _driver_setup(self):
        self.interface.rdy.value = 0

    async def _driver_on_rising_edge(self):
        if self.interface.rdy.value == 1 and self.interface.val.value == 1:
            self.queue.put_nowait(self.bus_data_type.from_signal(self.interface.data))
        
        await FallingEdge(top.clk)
        
        can_consume = self.enabled and not self.queue.full()
        if self.interface.rdy_is_ack:
            self.interface.rdy.value = self.interface.val.value == 1 and can_consume
        else:
            self.interface.rdy.value = can_consume

    async def _driver_cleanup(self):
        self.interface.rdy.setimmediatevalue(0)

class AbstractTB(AbstractAsyncContextManager):
    logger: Logger
    clock_task: Task
    tasks: Mapping[str, TBTask]

    def __init__(
        self,
        dut: SimHandleBase,
        tasks: Mapping[str, TBTask]=dict(),
    ):
        super().__init__()

        self.logger = LOGGER.getChild(self.__class__.__name__)
        self.clock_task = cocotb.create_task(Clock(dut.clk, 10, 'ns').start())
        
        self.tasks = tasks

        for k, v in self.tasks.items():
            setattr(self, k, v)

    @override
    async def __aenter__(self) -> Self:
        self.logger.info("Setting up TB...")

        await cocotb.start(self.clock_task)
        await reset()

        for task in self.tasks.values():
            await task.start()

        self.logger.info("TB setup done")

        return self

    @override
    async def __aexit__(self, exc_type, exc_value, traceback) -> bool:
        self.logger.info(f"Cleaning up...")
        
        for task in self.tasks.values():
            await task.stop()

        self.clock_task.kill()

        self.logger.info(f"Cleanup done")

        return False


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
