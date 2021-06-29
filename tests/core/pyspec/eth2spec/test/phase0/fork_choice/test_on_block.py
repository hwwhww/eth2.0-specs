import random

from eth2spec.utils.ssz.ssz_impl import hash_tree_root
from eth2spec.test.context import MINIMAL, spec_state_test, with_all_phases, with_presets
from eth2spec.test.helpers.attestations import (
    next_epoch_with_attestations,
    next_slots_with_attestations,
    state_transition_with_full_block,
    state_transition_with_full_attestations_block,
)
from eth2spec.test.helpers.block import (
    build_empty_block_for_next_slot,
    build_empty_block,
    transition_unsigned_block,
    sign_block,
)
from eth2spec.test.helpers.fork_choice import (
    get_genesis_forkchoice_store_and_block,
    on_tick_and_append_step,
    add_block,
    tick_and_add_block,
    apply_next_epoch_with_attestations,
    apply_next_slots_with_attestations,
)
from eth2spec.test.helpers.state import (
    next_epoch,
    next_slots,
    state_transition_and_sign_block,
    transition_to,
)


rng = random.Random(2020)


def _drop_random_one_third(_slot, _index, indices):
    committee_len = len(indices)
    assert committee_len >= 3
    filter_len = committee_len // 3
    participant_count = committee_len - filter_len
    return rng.sample(indices, participant_count)


@with_all_phases
@spec_state_test
def test_basic(spec, state):
    test_steps = []
    # Initialization
    store, anchor_block = get_genesis_forkchoice_store_and_block(spec, state)
    yield 'anchor_state', state
    yield 'anchor_block', anchor_block
    current_time = state.slot * spec.config.SECONDS_PER_SLOT + store.genesis_time
    on_tick_and_append_step(spec, store, current_time, test_steps)
    assert store.time == current_time

    # On receiving a block of `GENESIS_SLOT + 1` slot
    block = build_empty_block_for_next_slot(spec, state)
    signed_block = state_transition_and_sign_block(spec, state, block)
    yield from tick_and_add_block(spec, store, signed_block, test_steps)
    assert spec.get_head(store) == signed_block.message.hash_tree_root()

    # On receiving a block of next epoch
    store.time = current_time + spec.config.SECONDS_PER_SLOT * spec.SLOTS_PER_EPOCH
    block = build_empty_block(spec, state, state.slot + spec.SLOTS_PER_EPOCH)
    signed_block = state_transition_and_sign_block(spec, state, block)
    yield from tick_and_add_block(spec, store, signed_block, test_steps)
    assert spec.get_head(store) == signed_block.message.hash_tree_root()

    yield 'steps', test_steps

    # TODO: add tests for justified_root and finalized_root


@with_all_phases
@spec_state_test
@with_presets([MINIMAL], reason="too slow")
def test_on_block_checkpoints(spec, state):
    test_steps = []
    # Initialization
    store, anchor_block = get_genesis_forkchoice_store_and_block(spec, state)
    yield 'anchor_state', state
    yield 'anchor_block', anchor_block
    current_time = state.slot * spec.config.SECONDS_PER_SLOT + store.genesis_time
    on_tick_and_append_step(spec, store, current_time, test_steps)
    assert store.time == current_time

    # Run for 1 epoch with full attestations
    next_epoch(spec, state)
    on_tick_and_append_step(spec, store, store.time + state.slot * spec.config.SECONDS_PER_SLOT, test_steps)

    state, store, last_signed_block = yield from apply_next_epoch_with_attestations(
        spec, state, store, True, False, test_steps=test_steps)
    last_block_root = hash_tree_root(last_signed_block.message)
    assert spec.get_head(store) == last_block_root

    # Forward 1 epoch
    next_epoch(spec, state)
    on_tick_and_append_step(spec, store, store.time + state.slot * spec.config.SECONDS_PER_SLOT, test_steps)

    # Mock the finalized_checkpoint and build a block on it
    fin_state = store.block_states[last_block_root].copy()
    fin_state.finalized_checkpoint = store.block_states[last_block_root].current_justified_checkpoint.copy()

    block = build_empty_block_for_next_slot(spec, fin_state)
    signed_block = state_transition_and_sign_block(spec, fin_state.copy(), block)
    yield from tick_and_add_block(spec, store, signed_block, test_steps)
    assert spec.get_head(store) == signed_block.message.hash_tree_root()
    yield 'steps', test_steps


@with_all_phases
@spec_state_test
def test_on_block_future_block(spec, state):
    test_steps = []
    # Initialization
    store, anchor_block = get_genesis_forkchoice_store_and_block(spec, state)
    yield 'anchor_state', state
    yield 'anchor_block', anchor_block
    current_time = state.slot * spec.config.SECONDS_PER_SLOT + store.genesis_time
    on_tick_and_append_step(spec, store, current_time, test_steps)
    assert store.time == current_time

    # Do NOT tick time to `GENESIS_SLOT + 1` slot
    # Fail receiving block of `GENESIS_SLOT + 1` slot
    block = build_empty_block_for_next_slot(spec, state)
    signed_block = state_transition_and_sign_block(spec, state, block)
    yield from add_block(spec, store, signed_block, test_steps, valid=False)

    yield 'steps', test_steps


@with_all_phases
@spec_state_test
def test_on_block_bad_parent_root(spec, state):
    test_steps = []
    # Initialization
    store, anchor_block = get_genesis_forkchoice_store_and_block(spec, state)
    yield 'anchor_state', state
    yield 'anchor_block', anchor_block
    current_time = state.slot * spec.config.SECONDS_PER_SLOT + store.genesis_time
    on_tick_and_append_step(spec, store, current_time, test_steps)
    assert store.time == current_time

    # Fail receiving block of `GENESIS_SLOT + 1` slot
    block = build_empty_block_for_next_slot(spec, state)
    transition_unsigned_block(spec, state, block)
    block.state_root = state.hash_tree_root()

    block.parent_root = b'\x45' * 32

    signed_block = sign_block(spec, state, block)

    yield from add_block(spec, store, signed_block, test_steps, valid=False)

    yield 'steps', test_steps


@with_all_phases
@spec_state_test
@with_presets([MINIMAL], reason="too slow")
def test_on_block_before_finalized(spec, state):
    test_steps = []
    # Initialization
    store, anchor_block = get_genesis_forkchoice_store_and_block(spec, state)
    yield 'anchor_state', state
    yield 'anchor_block', anchor_block
    current_time = state.slot * spec.config.SECONDS_PER_SLOT + store.genesis_time
    on_tick_and_append_step(spec, store, current_time, test_steps)
    assert store.time == current_time

    # Fork
    another_state = state.copy()

    # Create a finalized chain
    for _ in range(4):
        state, store, _ = yield from apply_next_epoch_with_attestations(
            spec, state, store, True, False, test_steps=test_steps)
    assert store.finalized_checkpoint.epoch == 2

    # Fail receiving block of `GENESIS_SLOT + 1` slot
    block = build_empty_block_for_next_slot(spec, another_state)
    block.body.graffiti = b'\x12' * 32
    signed_block = state_transition_and_sign_block(spec, another_state, block)
    assert signed_block.message.hash_tree_root() not in store.blocks
    yield from tick_and_add_block(spec, store, signed_block, test_steps, valid=False)

    yield 'steps', test_steps


@with_all_phases
@spec_state_test
@with_presets([MINIMAL], reason="too slow")
def test_on_block_finalized_skip_slots(spec, state):
    test_steps = []
    # Initialization
    store, anchor_block = get_genesis_forkchoice_store_and_block(spec, state)
    yield 'anchor_state', state
    yield 'anchor_block', anchor_block
    current_time = state.slot * spec.config.SECONDS_PER_SLOT + store.genesis_time
    on_tick_and_append_step(spec, store, current_time, test_steps)
    assert store.time == current_time

    # Create a finalized chain
    for _ in range(4):
        state, store, _ = yield from apply_next_epoch_with_attestations(
            spec, state, store, True, False, test_steps=test_steps)
    assert store.finalized_checkpoint.epoch == 2

    # Another chain
    another_state = store.block_states[store.finalized_checkpoint.root].copy()
    # Build block that includes the skipped slots up to finality in chain
    block = build_empty_block(spec,
                              another_state,
                              spec.compute_start_slot_at_epoch(store.finalized_checkpoint.epoch) + 2)
    block.body.graffiti = b'\x12' * 32
    signed_block = state_transition_and_sign_block(spec, another_state, block)

    yield from tick_and_add_block(spec, store, signed_block, test_steps)

    yield 'steps', test_steps


@with_all_phases
@spec_state_test
@with_presets([MINIMAL], reason="too slow")
def test_on_block_finalized_skip_slots_not_in_skip_chain(spec, state):
    test_steps = []
    # Initialization
    transition_to(spec, state, state.slot + spec.SLOTS_PER_EPOCH - 1)
    block = build_empty_block_for_next_slot(spec, state)
    transition_unsigned_block(spec, state, block)
    block.state_root = state.hash_tree_root()
    store = spec.get_forkchoice_store(state, block)
    yield 'anchor_state', state
    yield 'anchor_block', block

    current_time = state.slot * spec.config.SECONDS_PER_SLOT + store.genesis_time
    on_tick_and_append_step(spec, store, current_time, test_steps)
    assert store.time == current_time

    pre_finalized_checkpoint_epoch = store.finalized_checkpoint.epoch

    # Finalized
    for _ in range(3):
        state, store, _ = yield from apply_next_epoch_with_attestations(
            spec, state, store, True, False, test_steps=test_steps)
    assert store.finalized_checkpoint.epoch == pre_finalized_checkpoint_epoch + 1

    # Now build a block at later slot than finalized epoch
    # Includes finalized block in chain, but not at appropriate skip slot
    pre_state = store.block_states[block.hash_tree_root()].copy()
    block = build_empty_block(spec,
                              state=pre_state,
                              slot=spec.compute_start_slot_at_epoch(store.finalized_checkpoint.epoch) + 2)
    block.body.graffiti = b'\x12' * 32
    signed_block = sign_block(spec, pre_state, block)
    yield from tick_and_add_block(spec, store, signed_block, test_steps, valid=False)

    yield 'steps', test_steps


@with_all_phases
@spec_state_test
def test_on_block_update_justified_checkpoint_within_safe_slots(spec, state):
    """
    Test `should_update_justified_checkpoint`:
    compute_slots_since_epoch_start(get_current_slot(store)) < SAFE_SLOTS_TO_UPDATE_JUSTIFIED
    """
    test_steps = []
    # Initialization
    store, anchor_block = get_genesis_forkchoice_store_and_block(spec, state)
    yield 'anchor_state', state
    yield 'anchor_block', anchor_block
    current_time = state.slot * spec.config.SECONDS_PER_SLOT + store.genesis_time
    on_tick_and_append_step(spec, store, current_time, test_steps)
    assert store.time == current_time

    # Skip epoch 0 & 1
    for _ in range(2):
        next_epoch(spec, state)
    # Fill epoch 2
    state, store, _ = yield from apply_next_epoch_with_attestations(
        spec, state, store, True, False, test_steps=test_steps)
    assert state.finalized_checkpoint.epoch == store.finalized_checkpoint.epoch == 0
    assert state.current_justified_checkpoint.epoch == store.justified_checkpoint.epoch == 2
    # Skip epoch 3 & 4
    for _ in range(2):
        next_epoch(spec, state)
    # Epoch 5: Attest current epoch
    state, store, _ = yield from apply_next_epoch_with_attestations(
        spec, state, store, True, False, participation_fn=_drop_random_one_third, test_steps=test_steps)
    assert state.finalized_checkpoint.epoch == store.finalized_checkpoint.epoch == 0
    assert state.current_justified_checkpoint.epoch == 2
    assert store.justified_checkpoint.epoch == 2
    assert state.current_justified_checkpoint == store.justified_checkpoint

    # Skip epoch 6
    next_epoch(spec, state)

    pre_state = state.copy()

    # Build a block to justify epoch 5
    signed_block = state_transition_with_full_block(spec, state, True, True)
    assert state.finalized_checkpoint.epoch == 0
    assert state.current_justified_checkpoint.epoch == 5
    assert state.current_justified_checkpoint.epoch > store.justified_checkpoint.epoch
    assert spec.get_current_slot(store) % spec.SLOTS_PER_EPOCH < spec.SAFE_SLOTS_TO_UPDATE_JUSTIFIED
    # Run on_block
    yield from tick_and_add_block(spec, store, signed_block, test_steps)
    # Ensure justified_checkpoint has been changed but finality is unchanged
    assert store.justified_checkpoint.epoch == 5
    assert store.justified_checkpoint == state.current_justified_checkpoint
    assert store.finalized_checkpoint.epoch == pre_state.finalized_checkpoint.epoch == 0

    yield 'steps', test_steps


@with_all_phases
@with_presets([MINIMAL], reason="It assumes that `MAX_ATTESTATIONS` >= 2/3 attestations of an epoch")
@spec_state_test
def test_on_block_outside_safe_slots_but_finality(spec, state):
    """
    Test `should_update_justified_checkpoint` case
    - compute_slots_since_epoch_start(get_current_slot(store)) > SAFE_SLOTS_TO_UPDATE_JUSTIFIED
    - new_justified_checkpoint and store.justified_checkpoint.root are NOT conflicting

    Thus should_update_justified_checkpoint returns True.

    Part of this script is similar to `test_new_justified_is_later_than_store_justified`.
    """
    test_steps = []
    # Initialization
    store, anchor_block = get_genesis_forkchoice_store_and_block(spec, state)
    yield 'anchor_state', state
    yield 'anchor_block', anchor_block
    current_time = state.slot * spec.config.SECONDS_PER_SLOT + store.genesis_time
    on_tick_and_append_step(spec, store, current_time, test_steps)
    assert store.time == current_time

    # Skip epoch 0
    next_epoch(spec, state)
    # Fill epoch 1 to 3, attest current epoch
    for _ in range(3):
        state, store, _ = yield from apply_next_epoch_with_attestations(
            spec, state, store, True, False, test_steps=test_steps)
    assert state.finalized_checkpoint.epoch == store.finalized_checkpoint.epoch == 2
    assert state.current_justified_checkpoint.epoch == store.justified_checkpoint.epoch == 3

    # Skip epoch 4-6
    for _ in range(3):
        next_epoch(spec, state)

    # epoch 7
    state, store, _ = yield from apply_next_epoch_with_attestations(
        spec, state, store, True, True, test_steps=test_steps)
    assert state.finalized_checkpoint.epoch == 2
    assert state.current_justified_checkpoint.epoch == 7

    # epoch 8, attest the first 5 blocks
    state, store, _ = yield from apply_next_slots_with_attestations(
        spec, state, store, 5, True, True, test_steps)
    assert state.finalized_checkpoint.epoch == store.finalized_checkpoint.epoch == 2
    assert state.current_justified_checkpoint.epoch == store.justified_checkpoint.epoch == 7

    # Propose a block at epoch 9, 5th slot
    next_epoch(spec, state)
    next_slots(spec, state, 4)
    signed_block = state_transition_with_full_attestations_block(spec, state, True, True)
    yield from tick_and_add_block(spec, store, signed_block, test_steps)
    assert state.finalized_checkpoint.epoch == store.finalized_checkpoint.epoch == 2
    assert state.current_justified_checkpoint.epoch == store.justified_checkpoint.epoch == 7

    # Propose an empty block at epoch 10, SAFE_SLOTS_TO_UPDATE_JUSTIFIED + 2 slot
    # This block would trigger justification and finality updates on store
    next_epoch(spec, state)
    next_slots(spec, state, 4)
    block = build_empty_block_for_next_slot(spec, state)
    signed_block = state_transition_and_sign_block(spec, state, block)
    assert state.finalized_checkpoint.epoch == 7
    assert state.current_justified_checkpoint.epoch == 8
    # Step time past safe slots and run on_block
    if store.time < spec.compute_time_at_slot(state, signed_block.message.slot):
        time = store.genesis_time + signed_block.message.slot * spec.config.SECONDS_PER_SLOT
        on_tick_and_append_step(spec, store, time, test_steps)
    assert spec.get_current_slot(store) % spec.SLOTS_PER_EPOCH >= spec.SAFE_SLOTS_TO_UPDATE_JUSTIFIED
    yield from add_block(spec, store, signed_block, test_steps)

    # Ensure justified_checkpoint finality has been changed
    assert store.finalized_checkpoint.epoch == 7
    assert store.finalized_checkpoint == state.finalized_checkpoint
    assert store.justified_checkpoint.epoch == 8
    assert store.justified_checkpoint == state.current_justified_checkpoint

    yield 'steps', test_steps


@with_all_phases
@with_presets([MINIMAL], reason="It assumes that `MAX_ATTESTATIONS` >= 2/3 attestations of an epoch")
@spec_state_test
def test_new_justified_is_later_than_store_justified(spec, state):
    """
    J: Justified
    F: Finalized
    fork_1_state (forked from genesis):
        epoch
        [0] <- [1] <- [2] <- [3] <- [4]
         F                    J

    fork_2_state (forked from fork_1_state's epoch 2):
        epoch
                       └──── [3] <- [4] <- [5] <- [6]
         F                           J

    fork_3_state (forked from genesis):
        [0] <- [1] <- [2] <- [3] <- [4] <- [5]
                              F      J
    """
    # The 1st fork, from genesis
    fork_1_state = state.copy()
    # The 3rd fork, from genesis
    fork_3_state = state.copy()

    test_steps = []
    # Initialization
    store, anchor_block = get_genesis_forkchoice_store_and_block(spec, state)
    yield 'anchor_state', state
    yield 'anchor_block', anchor_block
    current_time = state.slot * spec.config.SECONDS_PER_SLOT + store.genesis_time
    on_tick_and_append_step(spec, store, current_time, test_steps)
    assert store.time == current_time

    # ----- Process fork_1_state
    # Skip epoch 0
    next_epoch(spec, fork_1_state)
    # Fill epoch 1 with previous epoch attestations
    fork_1_state, store, _ = yield from apply_next_epoch_with_attestations(
        spec, fork_1_state, store, False, True, test_steps=test_steps)

    # Fork `fork_2_state` at the start of epoch 2
    fork_2_state = fork_1_state.copy()
    assert spec.get_current_epoch(fork_2_state) == 2

    # Skip epoch 2
    next_epoch(spec, fork_1_state)
    # # Fill epoch 3 & 4 with previous epoch attestations
    for _ in range(2):
        fork_1_state, store, _ = yield from apply_next_epoch_with_attestations(
            spec, fork_1_state, store, False, True, test_steps=test_steps)

    assert fork_1_state.finalized_checkpoint.epoch == store.finalized_checkpoint.epoch == 0
    assert fork_1_state.current_justified_checkpoint.epoch == store.justified_checkpoint.epoch == 3
    assert store.justified_checkpoint.hash_tree_root() == fork_1_state.current_justified_checkpoint.hash_tree_root()

    # ------ fork_2_state: Create a chain to set store.best_justified_checkpoint
    # NOTE: The goal is to make `store.best_justified_checkpoint.epoch > store.justified_checkpoint.epoch`
    all_blocks = []

    # Proposed an empty block at epoch 2, 1st slot
    block = build_empty_block_for_next_slot(spec, fork_2_state)
    signed_block = state_transition_and_sign_block(spec, fork_2_state, block)
    yield from tick_and_add_block(spec, store, signed_block, test_steps)
    assert fork_2_state.current_justified_checkpoint.epoch == 0

    # Skip to epoch 4
    for _ in range(2):
        next_epoch(spec, fork_2_state)
        assert fork_2_state.current_justified_checkpoint.epoch == 0

    # Propose a block at epoch 4, 5th slot
    # Propose a block at epoch 5, 5th slot
    for _ in range(2):
        next_epoch(spec, fork_2_state)
        next_slots(spec, fork_2_state, 4)
        signed_block = state_transition_with_full_attestations_block(spec, fork_2_state, True, True)
        yield from tick_and_add_block(spec, store, signed_block, test_steps)
        assert fork_2_state.current_justified_checkpoint.epoch == 0

    # Propose a block at epoch 6, SAFE_SLOTS_TO_UPDATE_JUSTIFIED + 2 slot
    next_epoch(spec, fork_2_state)
    next_slots(spec, fork_2_state, spec.SAFE_SLOTS_TO_UPDATE_JUSTIFIED + 2)
    signed_block = state_transition_with_full_attestations_block(spec, fork_2_state, True, True)
    assert fork_2_state.finalized_checkpoint.epoch == 0
    assert fork_2_state.current_justified_checkpoint.epoch == 5
    # Check SAFE_SLOTS_TO_UPDATE_JUSTIFIED
    spec.on_tick(store, store.genesis_time + fork_2_state.slot * spec.config.SECONDS_PER_SLOT)
    assert spec.compute_slots_since_epoch_start(spec.get_current_slot(store)) >= spec.SAFE_SLOTS_TO_UPDATE_JUSTIFIED
    # Run on_block
    yield from add_block(spec, store, signed_block, test_steps)
    assert store.finalized_checkpoint.epoch == 0
    assert store.justified_checkpoint.epoch == 3
    assert store.best_justified_checkpoint.epoch == 5

    # ------ fork_3_state: Create another chain to test the
    # "Update justified if new justified is later than store justified" case
    all_blocks = []
    for _ in range(3):
        next_epoch(spec, fork_3_state)

    # epoch 3
    _, signed_blocks, fork_3_state = next_epoch_with_attestations(spec, fork_3_state, True, True)
    all_blocks += signed_blocks
    assert fork_3_state.finalized_checkpoint.epoch == 0

    # epoch 4, attest the first 5 blocks
    _, blocks, fork_3_state = next_slots_with_attestations(spec, fork_3_state, 5, True, True)
    all_blocks += blocks.copy()
    assert fork_3_state.finalized_checkpoint.epoch == 0

    # Propose a block at epoch 5, 5th slot
    next_epoch(spec, fork_3_state)
    next_slots(spec, fork_3_state, 4)
    signed_block = state_transition_with_full_block(spec, fork_3_state, True, True)
    all_blocks.append(signed_block.copy())
    assert fork_3_state.finalized_checkpoint.epoch == 0

    # Propose a block at epoch 6, 5th slot
    next_epoch(spec, fork_3_state)
    next_slots(spec, fork_3_state, 4)
    signed_block = state_transition_with_full_block(spec, fork_3_state, True, True)
    all_blocks.append(signed_block.copy())
    assert fork_3_state.finalized_checkpoint.epoch == 3
    assert fork_3_state.current_justified_checkpoint.epoch == 4

    # FIXME: pending on the `on_block`, `on_attestation` fix
    # # Apply blocks of `fork_3_state` to `store`
    # for block in all_blocks:
    #     if store.time < spec.compute_time_at_slot(fork_2_state, block.message.slot):
    #         spec.on_tick(store, store.genesis_time + block.message.slot * spec.config.SECONDS_PER_SLOT)
    #     # valid_attestations=False because the attestations are outdated (older than previous epoch)
    #     yield from add_block(spec, store, block, test_steps, allow_invalid_attestations=False)

    # assert store.finalized_checkpoint.hash_tree_root() == fork_3_state.finalized_checkpoint.hash_tree_root()
    # assert (store.justified_checkpoint.hash_tree_root()
    #         == fork_3_state.current_justified_checkpoint.hash_tree_root()
    #         != store.best_justified_checkpoint.hash_tree_root())
    # assert (store.best_justified_checkpoint.hash_tree_root()
    #         == fork_2_state.current_justified_checkpoint.hash_tree_root())

    yield 'steps', test_steps


@with_all_phases
@spec_state_test
def test_new_finalized_slot_is_not_justified_checkpoint_ancestor(spec, state):
    """
    J: Justified
    F: Finalized
    state (forked from genesis):
        epoch
        [0] <- [1] <- [2] <- [3] <- [4] <- [5]
         F                    J

    another_state (forked from epoch 0):
         └──── [1] <- [2] <- [3] <- [4] <- [5]
                       F      J
    """
    test_steps = []
    # Initialization
    store, anchor_block = get_genesis_forkchoice_store_and_block(spec, state)
    yield 'anchor_state', state
    yield 'anchor_block', anchor_block
    current_time = state.slot * spec.config.SECONDS_PER_SLOT + store.genesis_time
    on_tick_and_append_step(spec, store, current_time, test_steps)
    assert store.time == current_time

    # ----- Process state
    # Goal: make `store.finalized_checkpoint.epoch == 0` and `store.justified_checkpoint.epoch == 3`
    # Skip epoch 0
    next_epoch(spec, state)

    # Forking another_state
    another_state = state.copy()

    # Fill epoch 1 with previous epoch attestations
    state, store, _ = yield from apply_next_epoch_with_attestations(
        spec, state, store, False, True, test_steps=test_steps)
    # Skip epoch 2
    next_epoch(spec, state)
    # Fill epoch 3 & 4 with previous epoch attestations
    for _ in range(2):
        state, store, _ = yield from apply_next_epoch_with_attestations(
            spec, state, store, False, True, test_steps=test_steps)

    assert state.finalized_checkpoint.epoch == store.finalized_checkpoint.epoch == 0
    assert state.current_justified_checkpoint.epoch == store.justified_checkpoint.epoch == 3
    assert store.justified_checkpoint.hash_tree_root() == state.current_justified_checkpoint.hash_tree_root()

    # Create another chain
    # Goal: make `another_state.finalized_checkpoint.epoch == 2` and `another_state.justified_checkpoint.epoch == 3`
    all_blocks = []
    # Fill epoch 1 & 2 with previous + current epoch attestations
    for _ in range(3):
        _, signed_blocks, another_state = next_epoch_with_attestations(spec, another_state, True, True)
        all_blocks += signed_blocks

    assert another_state.finalized_checkpoint.epoch == 2
    assert another_state.current_justified_checkpoint.epoch == 3
    assert state.finalized_checkpoint.hash_tree_root() != another_state.finalized_checkpoint.hash_tree_root()
    assert (
        state.current_justified_checkpoint.hash_tree_root()
        != another_state.current_justified_checkpoint.hash_tree_root()
    )
    # pre_store_justified_checkpoint_root = store.justified_checkpoint.root

    # FIXME: pending on the `on_block`, `on_attestation` fix
    # # Apply blocks of `another_state` to `store`
    # for block in all_blocks:
    #     # NOTE: Do not call `on_tick` here
    #     yield from add_block(spec, store, block, test_steps, allow_invalid_attestations=True)

    # finalized_slot = spec.compute_start_slot_at_epoch(store.finalized_checkpoint.epoch)
    # ancestor_at_finalized_slot = spec.get_ancestor(store, pre_store_justified_checkpoint_root, finalized_slot)
    # assert ancestor_at_finalized_slot != store.finalized_checkpoint.root

    # assert store.finalized_checkpoint.hash_tree_root() == another_state.finalized_checkpoint.hash_tree_root()
    # assert store.justified_checkpoint.hash_tree_root() == another_state.current_justified_checkpoint.hash_tree_root()

    yield 'steps', test_steps


@with_all_phases
@spec_state_test
def test_new_finalized_slot_is_justified_checkpoint_ancestor(spec, state):
    """
    J: Justified
    F: Finalized
    state:
        epoch
        [0] <- [1] <- [2] <- [3] <- [4] <- [5]
                       F             J

    another_state (forked from state at epoch 3):
                              └──── [4] <- [5]
                              F      J
    """
    test_steps = []
    # Initialization
    store, anchor_block = get_genesis_forkchoice_store_and_block(spec, state)
    yield 'anchor_state', state
    yield 'anchor_block', anchor_block
    current_time = state.slot * spec.config.SECONDS_PER_SLOT + store.genesis_time
    on_tick_and_append_step(spec, store, current_time, test_steps)
    assert store.time == current_time

    # Process state
    next_epoch(spec, state)
    spec.on_tick(store, store.genesis_time + state.slot * spec.config.SECONDS_PER_SLOT)

    state, store, _ = yield from apply_next_epoch_with_attestations(
        spec, state, store, False, True, test_steps=test_steps)

    state, store, _ = yield from apply_next_epoch_with_attestations(
        spec, state, store, True, False, test_steps=test_steps)
    next_epoch(spec, state)

    for _ in range(2):
        state, store, _ = yield from apply_next_epoch_with_attestations(
            spec, state, store, False, True, test_steps=test_steps)

    assert state.finalized_checkpoint.epoch == store.finalized_checkpoint.epoch == 2
    assert state.current_justified_checkpoint.epoch == store.justified_checkpoint.epoch == 4
    assert store.justified_checkpoint.hash_tree_root() == state.current_justified_checkpoint.hash_tree_root()

    # Create another chain
    # Forking from epoch 3
    all_blocks = []
    slot = spec.compute_start_slot_at_epoch(3)
    block_root = spec.get_block_root_at_slot(state, slot)
    another_state = store.block_states[block_root].copy()
    for _ in range(2):
        _, signed_blocks, another_state = next_epoch_with_attestations(spec, another_state, True, True)
        all_blocks += signed_blocks

    assert another_state.finalized_checkpoint.epoch == 3
    assert another_state.current_justified_checkpoint.epoch == 4

    pre_store_justified_checkpoint_root = store.justified_checkpoint.root
    for block in all_blocks:
        # FIXME: Once `on_block` and `on_attestation` logic is fixed,
        # fix test case and remove allow_invalid_attestations flag
        yield from tick_and_add_block(spec, store, block, test_steps, allow_invalid_attestations=True)

    finalized_slot = spec.compute_start_slot_at_epoch(store.finalized_checkpoint.epoch)
    ancestor_at_finalized_slot = spec.get_ancestor(store, pre_store_justified_checkpoint_root, finalized_slot)
    assert ancestor_at_finalized_slot == store.finalized_checkpoint.root

    assert store.finalized_checkpoint.hash_tree_root() == another_state.finalized_checkpoint.hash_tree_root()
    assert store.justified_checkpoint.hash_tree_root() != another_state.current_justified_checkpoint.hash_tree_root()

    yield 'steps', test_steps