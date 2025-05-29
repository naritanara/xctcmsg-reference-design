from contextlib import AbstractAsyncContextManager, contextmanager
from enum import Enum
import logging

from logging import Logger
from os import environ
from re import sub
import sys
from types import TracebackType
from typing import AsyncGenerator, Awaitable, Callable, Literal, Mapping, MutableMapping, Optional, Protocol, override, ClassVar, Dict, Iterable, Self, Type, Any, runtime_checkable
from functools import reduce
from abc import ABC, abstractmethod
from dataclasses import dataclass, fields

import cocotb

from cocotb.binary import BinaryValue
from cocotb.handle import SimHandleBase
from cocotb.queue import Queue
from cocotb.task import Task
from cocotb.triggers import FallingEdge, Timer, Trigger
from cocotb.types.logic import Logic
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
requested_level = environ.get('XCTCMSG_LOG_LEVEL', 'INFO')
requested_level = logging.getLevelNamesMapping().get(requested_level, logging.INFO)
LOGGER.setLevel(requested_level)

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
                if not attr.is_resolvable:
                    ret += attr.binstr
                elif len(attr) == 1:
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

class TBCleanupException(ExceptionGroup):
    def __new__(cls, exceptions, task_repr: Optional[str]=None, message: Optional[str]=None) -> Self:
        if message is None:
            exception_text = 'Exceptions' if len(exceptions) > 1 else 'An exception'
            
            if task_repr is not None:
                message = f'{exception_text} occurred during cleanup of {task_repr}'
            else:
                message = f'{exception_text} occurred during cleanup of a task'

        return super().__new__(cls, message, exceptions)
    
    def __init__(self, exceptions, task_repr: Optional[str]=None, message: Optional[str]=None):
        pass

class TBCleanupAssertionError(TBCleanupException):
    def __new__(cls, exception: Exception, task_repr: str):
        self = super().__new__(cls, [exception], message=f'A cleanup-stage assertion failed in {task_repr}')
        return self

class TBTaskFinalVerificationFailures(ExceptionGroup):
    def derive(self, excs):
        return TBTaskFinalVerificationFailures(self.message, excs)

class TBTask(ABC):
    __task: Task
    __stop_event: Optional[triggers.Event]
    subtasks: Iterable['TBTask']
    
    def __init__(self, *, use_kill: bool=False, subtasks: Iterable['TBTask']=[]):
        self.__task = cocotb.create_task(self._task_coroutine())
        self.__stop_event = None if use_kill else triggers.Event()
        self.subtasks = subtasks
    
    @property
    def _stop_event(self) -> triggers.Event:
        if self.__stop_event is None:
            raise ValueError("There is no stop event, this task must be killed")
        return self.__stop_event
    
    @abstractmethod
    async def _task_coroutine(self):
        pass
    
    async def start(self):
        for task in self.subtasks:
            await task.start()
            
        await cocotb.start(self.__task)
    
    # For verification of end conditions
    async def on_test_finish(self):
        pass

    async def stop(self) -> Optional[TBCleanupException]:
        exceptions = []
        subtask_raised = False
        
        if self.__stop_event is None:
            self.__task.kill()
        else:
            self.__stop_event.set()
            await self.__task.join()
        
        for task in self.subtasks:
            e = await task.stop()
            if e is not None:
                exceptions.append(e)
                subtask_raised = True
        
        try:
            await self.on_test_finish()
        except AssertionError as e:
            exceptions.append(TBCleanupAssertionError(e, str(self)))
        except Exception as e:
            exceptions.append(TBCleanupException([e], str(self)))
        
        if len(exceptions) == 1 and not subtask_raised:
            return exceptions[0]
        
        if exceptions:
            return TBCleanupException(exceptions, str(self))

# Abstract away clock details (clock could be a fake signal)
class AbstractClock(TBTask):
    period_ns: int
    
    def __init__(self, period_ns: int):
        super().__init__()
        
        self.period_ns = period_ns
    
    @abstractmethod
    def rising_edge(self) -> Trigger:
        pass
    
    @abstractmethod
    def falling_edge(self) -> Trigger:
        pass

class FakeClock(AbstractClock):
    _rising_edge: triggers.Event
    _falling_edge: triggers.Event
    
    def __init__(self, period_ns: int):
        super().__init__(period_ns)
        
        self._rising_edge = triggers.Event()
        self._falling_edge = triggers.Event()
    
    @override
    async def _task_coroutine(self):
        stop_trigger = self._stop_event.wait()
        semi_period = Decimal(self.period_ns / 2)
        state = True
        
        while not self._stop_event.is_set():
            state = not state
            
            if state:
                self._rising_edge.set()
                self._rising_edge.clear()
            else:
                self._falling_edge.set()
                self._falling_edge.clear()
            
            await triggers.First(triggers.Timer(semi_period, 'ns'), stop_trigger)
    
    @override
    def rising_edge(self) -> Trigger:
        return self._rising_edge.wait()
    
    @override
    def falling_edge(self) -> Trigger:
        return self._falling_edge.wait()

class RealClock(AbstractClock):
    task: Task
    _rising_edge: Trigger
    _falling_edge: Trigger
    
    def __init__(self, clk: SimHandleBase, period_ns: int):
        super().__init__(period_ns)
        
        self.task = cocotb.create_task(Clock(clk, self.period_ns, 'ns').start())
        self._rising_edge = triggers.RisingEdge(clk)
        self._falling_edge = triggers.FallingEdge(clk)
    
    @override
    async def _task_coroutine(self):
        await cocotb.start(self.task)
        
        await self._stop_event.wait()

        self.task.kill()
    
    @override
    def rising_edge(self) -> Trigger:
        return self._rising_edge
    
    @override
    def falling_edge(self) -> Trigger:
        return self._falling_edge

@runtime_checkable
class NeedsClock(Protocol):
    clock: AbstractClock

class ClockedTBTask(TBTask, NeedsClock):
    clock: AbstractClock

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

class ValRdyMonitor[Data: SVStruct](ClockedTBTask):
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

        next_iteration_trigger = triggers.First(self.clock.rising_edge(), self._stop_event.wait())

        while not self._stop_event.is_set():
            if self.interface.rdy.value == 1 and self.interface.val.value == 1:
                value = self.bus_data_type.from_signal(self.interface.data)
                self.logger.debug(f"{self.interface.producer_name} -> {self.interface.consumer_name}: {value}")

            await next_iteration_trigger

        self.logger.info(f'Stopped monitoring the Valid-Ready interface between {self.interface.producer_name} and {self.interface.consumer_name}')

class ValRdyDriver[Data: SVStruct](ClockedTBTask):
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

        next_iteration_trigger = triggers.First(self.clock.rising_edge(), self._stop_event.wait())

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
    
    @override
    async def on_test_finish(self):
        assert self.queue_state == QueueState.EMPTY, f"There are elements left in a ValRdyDriver queue: {self.queue}"

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
        
        await self.clock.falling_edge()
        
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
        
        await self.clock.falling_edge()
        
        can_consume = self.enabled and not self.queue.full()
        if self.interface.rdy_is_ack:
            self.interface.rdy.value = self.interface.val.value == 1 and can_consume
        else:
            self.interface.rdy.value = can_consume

    async def _driver_cleanup(self):
        self.interface.rdy.setimmediatevalue(0)

class TBFailure(ExceptionGroup):
    def derive(self, excs):
        return TBFailure(self.message, excs)

class AbstractTB(AbstractAsyncContextManager):
    logger: Logger
    tasks: MutableMapping[str, TBTask]
    clock: AbstractClock
    _dut: SimHandleBase

    def __init__(
        self,
        dut: SimHandleBase,
        tasks: Mapping[str, TBTask]=dict(),
    ):
        super().__init__()

        self.logger = LOGGER.getChild(self.__class__.__name__)
        
        self.tasks = dict()
        
        if hasattr(dut, 'clk'):
            self.add_task('clock', RealClock(dut.clk, 10))
        else:
            self.add_task('clock', FakeClock(10))

        for id, task in tasks.items():
            self.add_task(id, task)
        
        self._dut = dut
    
    def __recursively_fullfill_needs_clock(self, task: TBTask):
        if isinstance(task, NeedsClock):
            setattr(task, 'clock', self.clock)
        
        for subtask in task.subtasks:
            self.__recursively_fullfill_needs_clock(subtask)
    
    def add_task(self, id: str, task: TBTask):
        if id in self.tasks:
            raise ValueError(f'Task id [{id}] already in use')
        self.tasks[id] = task
        setattr(self, id, task)
        
        self.__recursively_fullfill_needs_clock(task)

    @property
    def dut(self):
        return self._dut.dut

    @override
    async def __aenter__(self) -> Self:
        setup_exceptions = []
        
        try:
            self.logger.info("Setting up TB...")
    
            await reset()
    
            for task in self.tasks.values():
                try:
                    await task.start()
                except Exception as e:
                    setup_exceptions.append(e)
    
            self.logger.info("TB setup done")
        except Exception as e:
            setup_exceptions.append(e)
        finally:
            if setup_exceptions:
                raise TBFailure('Test setup failed', setup_exceptions) from None

        return self
    
    async def __stop_tasks(self) -> Optional[TBTaskFinalVerificationFailures]:
        cleanup_exceptions = []
        
        # We must ensure the clock is killed last, otherwise the simulator may
        # detect a situation where no more signals are driven and crash
        task_ids = list(self.tasks.keys())
        if 'clock' in task_ids:
            task_ids.remove('clock')
            task_ids.append('clock')
        
        for id, task in [(id, self.tasks[id]) for id in task_ids]:
            cleanup_exception = await task.stop()
            if cleanup_exception:
                cleanup_exception.add_note(f'Raised in task [{id}]')
                cleanup_exceptions.append(cleanup_exception)
        
        if cleanup_exceptions:
            exception_text = 'Exceptions' if len(cleanup_exceptions) > 1 else 'An exception'
            return TBCleanupException(cleanup_exceptions, message=f'{exception_text} occurred during TB cleanup')

    @override
    async def __aexit__(self, exc_type, exc_value, traceback) -> bool:
        self.logger.info(f"Cleaning up...")
        
        exceptions = []
        if isinstance(exc_value, Exception):
            exc_value.add_note('Raised in TB body')
            if not isinstance(exc_value, AssertionError):
                exc_value.add_note('CRITICAL: Not an assertion error, test may be ill defined')
            exceptions.append(exc_value)
        
        final_verification_exceptions = await self.__stop_tasks()
        if final_verification_exceptions:
            exceptions.append(final_verification_exceptions)
        
        if exceptions:
            raise TBFailure('Test failed', exceptions) from None

        self.logger.info(f"Cleanup done")

        return False


async def reset():
    if not hasattr(top, 'rst_n'):
        return
    
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
