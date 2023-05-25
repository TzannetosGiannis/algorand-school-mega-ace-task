from pyteal import *
from beaker import *
from test import *
from beaker import sandbox, client
from algosdk import transaction
from algosdk.v2client import *

from algosdk import transaction
from algosdk.atomic_transaction_composer import (
    AtomicTransactionComposer,
    TransactionWithSigner,
)

from beaker import *


def send_asset_transfer_transaction(asa_id: Expr, receiver: Expr, amount: Expr):
    return Seq(
        InnerTxnBuilder.Execute(
            {
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: asa_id,
                TxnField.asset_receiver: receiver,
                TxnField.asset_amount: amount,
                TxnField.fee: Int(0),
            }
        )
    )


def send_opt_in_transaction(asa_id: Expr):
    return Seq(
        InnerTxnBuilder.Execute(
            {
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: asa_id,
                TxnField.asset_receiver: Global.current_application_address(),
                TxnField.asset_amount: Int(0),
                TxnField.fee: Int(0),
            }
        )
    )


class State:
    collateral_id = LocalStateValue(stack_type=TealType.uint64)
    borrowing_id = LocalStateValue(stack_type=TealType.uint64)
    amount = LocalStateValue(stack_type=TealType.uint64)
    duration = LocalStateValue(stack_type=TealType.uint64)
    interest = LocalStateValue(stack_type=TealType.uint64)  # 2 d.p.

    start = LocalStateValue(stack_type=TealType.uint64)
    lender = LocalStateValue(stack_type=TealType.bytes)


nft_as_collateral_app = Application("NFTasCollateral", state=State)


@nft_as_collateral_app.external
def opt_in_nft(axfer: abi.Asset):
    # opt in the application address to the nft
    return Seq(
        send_opt_in_transaction(axfer.asset_id()),
    )


@nft_as_collateral_app.opt_in()
def opt_in_borrower() -> Expr:
    return nft_as_collateral_app.initialize_local_state()


# Borrower
@nft_as_collateral_app.external
def request_loan(
    axfer: abi.AssetTransferTransaction,
    request_token: abi.Uint64,
    quantity: abi.Uint64,
    duration: abi.Uint64,
    interest: abi.Uint64,
):
    return Seq(
        # check that not other loan request is open for the user
        Assert(nft_as_collateral_app.state.collateral_id == Int(0)),
        # check that he sends the asset to this contract
        Assert(axfer.get().asset_receiver() == Global.current_application_address()),
        # check that it is one because we only have loans over nft , otherwise we can
        # extend the programme and store the data
        Assert(axfer.get().asset_amount() == Int(1)),
        # set local storage
        nft_as_collateral_app.state.borrowing_id.set(request_token.get()),
        nft_as_collateral_app.state.amount.set(quantity.get()),
        nft_as_collateral_app.state.duration.set(duration.get()),
        nft_as_collateral_app.state.interest.set(interest.get()),
        nft_as_collateral_app.state.collateral_id.set(axfer.get().xfer_asset()),
    )


@nft_as_collateral_app.external
def delete_request(asset: abi.Asset):
    # check if the loan has started

    return Seq(
        # check that no lender has accepted any loan
        Assert(App.optedIn(Txn.sender(), Global.current_application_id())),
        Assert(nft_as_collateral_app.state.lender == Bytes("")),
        # send back the collateral
        send_asset_transfer_transaction(
            nft_as_collateral_app.state.collateral_id, Txn.sender(), Int(1)
        ),
        # clear state
        clearState(),
    )


@Subroutine(TealType.none)
def clearState():
    return Seq(
        # fully clean the local storage of a user
        nft_as_collateral_app.state.amount.set(Int(0)),
        nft_as_collateral_app.state.borrowing_id.set(Int(0)),
        nft_as_collateral_app.state.collateral_id.set(Int(0)),
        nft_as_collateral_app.state.duration.set(Int(0)),
        nft_as_collateral_app.state.interest.set(Int(0)),
        nft_as_collateral_app.state.start.set(Int(0)),
        nft_as_collateral_app.state.lender.set(Bytes("")),
    )


@Subroutine(TealType.uint64)
def calculateInterest():
    return Return(
        # calculate seconds since borrow
        # myltiply by amount locker and divided byt total seconds of year
        # myltiply by the interest which is integer (example 5  for 0.05)
        nft_as_collateral_app.state.amount
        * (Global.latest_timestamp() - nft_as_collateral_app.state.start)
        / Int(31556926)
        * nft_as_collateral_app.state.interest
    )


@nft_as_collateral_app.external
def repay_loan(axfer: abi.AssetTransferTransaction, asset: abi.Asset):
    return Seq(
        # check that the assets are sent to the lender
        Assert(axfer.get().asset_receiver() == nft_as_collateral_app.state.lender),
        # check that the collateral is included
        Assert(
            axfer.get().asset_amount()
            >= nft_as_collateral_app.state.amount + calculateInterest()
        ),
        # check that the correct asset is included in the transfer transaction
        Assert(axfer.get().xfer_asset() == nft_as_collateral_app.state.borrowing_id),
        send_asset_transfer_transaction(
            nft_as_collateral_app.state.collateral_id, Txn.sender(), Int(1)
        ),
        # clear the state of the contract
        clearState(),
    )


# Lender
@nft_as_collateral_app.external
def accept_loan(borrower: abi.Account, axfer: abi.AssetTransferTransaction):
    return Seq(
        # check that the borrower is someone that has opted in the contract
        Assert(App.optedIn(borrower.address(), Global.current_application_id())),
        # check that the loan is not already accepted by other
        Assert(nft_as_collateral_app.state.lender[borrower.address()] == Bytes("")),
        # check that the transfer is going to the correct destination
        Assert(axfer.get().asset_receiver() == borrower.address()),
        # check that the lender is sending the correct amount in the transfer
        Assert(
            axfer.get().asset_amount()
            == nft_as_collateral_app.state.amount[borrower.address()]
        ),
        nft_as_collateral_app.state.lender[borrower.address()].set(Txn.sender()),
        # initial time of lending
        nft_as_collateral_app.state.start[borrower.address()].set(
            Global.latest_timestamp()
        ),
    )


@nft_as_collateral_app.external
def calculate_interest(*, output: abi.Uint64):
    return output.set(calculateInterest())


@nft_as_collateral_app.external
def liquidate_loan(address: abi.Account, asset: abi.Asset):
    return Seq(
        # check that the account we are going to liquidate is opted in the contract
        Assert(App.optedIn(address.address(), Global.current_application_id())),
        If(
            # check if the loan is still open
            nft_as_collateral_app.state.start[address.address()]
            + nft_as_collateral_app.state.duration[address.address()]
            < Global.latest_timestamp()
        )
        .Then(
            # check that the invoker of the contract is the one that has lend the money to borrower
            Assert(
                nft_as_collateral_app.state.lender[address.address()] == Txn.sender()
            ),
            # send the collateral to the lender
            send_asset_transfer_transaction(
                nft_as_collateral_app.state.collateral_id[address.address()],
                Txn.sender(),
                Int(1),
            ),
            # clear local storage of borrower
            nft_as_collateral_app.state.amount[address.address()].set(Int(0)),
            nft_as_collateral_app.state.borrowing_id[address.address()].set(Int(0)),
            nft_as_collateral_app.state.collateral_id[address.address()].set(Int(0)),
            nft_as_collateral_app.state.duration[address.address()].set(Int(0)),
            nft_as_collateral_app.state.interest[address.address()].set(Int(0)),
            nft_as_collateral_app.state.start[address.address()].set(Int(0)),
            nft_as_collateral_app.state.lender[address.address()].set(Bytes("")),
        )
        .Else(Approve()),
    )


if __name__ == "__main__":
    nft_as_collateral_app.build().export("./artifacts")

    accounts = sandbox.kmd.get_accounts()
    sender = accounts[0]
    sender2 = accounts[1]
    request_amount = 20000000

    algod_client = sandbox.get_algod_client()

    app_client = client.ApplicationClient(
        client=sandbox.get_algod_client(),
        app=nft_as_collateral_app,
        sender=sender.address,
        signer=sender.signer,
    )

    app_id, app_addr, txid = app_client.create()
    print(
        f"Step1: Created App with id: {app_id} and address addr: {app_addr} in tx: {txid}"
    )
    app_client.fund(100001 * consts.milli_algo)
    print(
        f"Info: Address {app_addr} has content {algod_client.account_info(app_addr).get('amount')} algos"
    )
    atc = AtomicTransactionComposer()

    # Create ASA
    asa_create_borrower = TransactionWithSigner(
        txn=transaction.AssetCreateTxn(
            sender=sender.address,
            total=1,
            decimals=0,
            default_frozen=False,
            unit_name="Borrower",
            asset_name="Borrower ASA",
            sp=app_client.get_suggested_params(),
        ),
        signer=sender.signer,
    )

    atc.add_transaction(asa_create_borrower)
    atc_result = atc.execute(sandbox.get_algod_client(), 3)
    actual_round = atc_result.confirmed_round
    caclulate_amount1 = algod_client.block_info(actual_round)["block"]["ts"]

    tx_id = atc_result.tx_ids[0]
    asa = sandbox.get_algod_client().pending_transaction_info(tx_id)["asset-index"]
    print(
        f"Info: Generated Asset {asa} at {tx_id} at {sender.address} with total supply 1"
    )
    # Create ASA lender
    asa2_supply = 10000000000
    atc2 = AtomicTransactionComposer()
    asa_create_lender = TransactionWithSigner(
        txn=transaction.AssetCreateTxn(
            sender=sender2.address,
            total=asa2_supply,
            decimals=0,
            default_frozen=False,
            unit_name="Lender",
            asset_name="Lender ASA",
            sp=app_client.get_suggested_params(),
        ),
        signer=sender2.signer,
    )

    atc2.add_transaction(asa_create_lender)
    tx_id = atc2.execute(sandbox.get_algod_client(), 3).tx_ids[0]
    asa2 = sandbox.get_algod_client().pending_transaction_info(tx_id)["asset-index"]
    print(
        f"Info: Generated Asset {asa2} at {tx_id} at {sender2.address} with total supply {asa2_supply}"
    )

    axfer = TransactionWithSigner(
        txn=transaction.AssetTransferTxn(
            sender=sender.address,
            receiver=app_addr,
            index=asa,
            amt=1,
            sp=app_client.get_suggested_params(),
        ),
        signer=sender.signer,
    )

    app_client.opt_in(
        sender=sender.address,
        signer=sender.signer,
    )
    print()
    print(f"Step 2: borrower {sender.address} opts in the contract")
    sp = app_client.get_suggested_params()
    sp.fee = sp.min_fee * 3
    app_client.call(
        opt_in_nft,
        sender=sender.address,
        signer=sender.signer,
        suggested_params=sp,
        axfer=asa,
    )
    print()
    print(f"Step 3: borrower {sender.address} opts in the contract the asset {asa}")
    loan_duration = 100000000
    interest = 5
    app_client.call(
        request_loan,
        request_token=asa2,  # fix this
        quantity=request_amount,
        duration=loan_duration,
        interest=interest,
        axfer=axfer,
        sender=sender.address,
        suggested_params=sp,
        signer=sender.signer,
    )
    print()
    print(
        f"Step 4: borrower {sender.address} requests loan for {loan_duration} seconds over {asa} ASA for {interest} unit per second interest"
    )

    app_client.call(
        opt_in_nft,
        sender=sender2.address,
        signer=sender2.signer,
        suggested_params=sp,
        axfer=asa2,
    )
    print(f"Info: lender {sender2.address} opts in the contract the {asa2} ASA")
    print(
        f"Info: borrowers {sender.address} local storage {app_client.get_local_state(sender.address)}"
    )

    # opt in user 1
    atc3 = AtomicTransactionComposer()
    axfer = TransactionWithSigner(
        txn=transaction.AssetTransferTxn(
            sender=sender.address,
            receiver=sender.address,
            index=asa2,
            amt=0,
            sp=sp,
        ),
        signer=sender.signer,
    )

    atc3.add_transaction(axfer)
    tx_id = atc3.execute(sandbox.get_algod_client(), 3).tx_ids[0]
    print(f"Info: borrower {sender.address} opts in  {asa2} ASA")
    atc4 = AtomicTransactionComposer()
    axfer = TransactionWithSigner(
        txn=transaction.AssetTransferTxn(
            sender=sender2.address,
            receiver=sender.address,
            index=asa2,
            amt=40000,
            sp=sp,
        ),
        signer=sender2.signer,
    )

    atc4.add_transaction(axfer)
    tx_id = atc4.execute(sandbox.get_algod_client(), 3).tx_ids[0]

    # opt in user 2 to asa
    atc5 = AtomicTransactionComposer()
    axfer = TransactionWithSigner(
        txn=transaction.AssetTransferTxn(
            sender=sender2.address,
            receiver=sender2.address,
            index=asa,
            amt=0,
            sp=sp,
        ),
        signer=sender2.signer,
    )
    print(f"Info: lender {sender2.address} opts in for {asa} ASA")
    atc5.add_transaction(axfer)
    atc5_result = atc5.execute(sandbox.get_algod_client(), 3)
    axfer = TransactionWithSigner(
        txn=transaction.AssetTransferTxn(
            sender=sender2.address,
            receiver=sender.address,
            index=asa2,
            amt=request_amount,
            sp=app_client.get_suggested_params(),
        ),
        signer=sender2.signer,
    )

    app_client.call(
        accept_loan,
        borrower=sender.address,
        sender=sender2.address,
        signer=sender2.signer,
        axfer=axfer,
    )
    print()
    print(f"Step 5: lender {sender2.address} accepts the loan")
    print(
        f"Info: borrowers {sender.address} local storage {app_client.get_local_state(sender.address)}"
    )
    return_value = app_client.call(
        calculate_interest, sender=sender.address, signer=sender.signer
    )
    # x3 factor is just because time is relevant in locanet , or seems so
    payed_interest = return_value.return_value * 3
    print(f"Info: Accumulater interest {payed_interest}")
    axfer = TransactionWithSigner(
        txn=transaction.AssetTransferTxn(
            sender=sender.address,
            receiver=sender2.address,
            index=asa2,
            amt=request_amount + payed_interest,
            sp=app_client.get_suggested_params(),
        ),
        signer=sender.signer,
    )

    app_acct_info = algod_client.account_info(sender.address)
    print(
        f"Info: after taken loan borrower {sender.address}",
        app_acct_info["assets"][-2:],
    )
    app_acct_info = algod_client.account_info(app_addr)
    print(f"Info: after taken loan app {app_addr}", app_acct_info["assets"])
    app_acct_info = algod_client.account_info(sender2.address)
    print(
        f"Info: after taken loan lender {sender2.address}", app_acct_info["assets"][-2:]
    )

    # action = "liquidate loan"
    # app_client.call(
    #     liquidate_loan,
    #     address=sender.address,
    #     asset=asa,
    #     signer=sender2.signer,
    #     sender=sender2.address,
    #     suggested_params=sp,
    # )
    # print()
    # print(
    #     f"Step6: lender liquidates {sender2.address} and gets the collateral {asa} ASA"
    # )

    action = "repay loan"
    app_client.call(
        repay_loan,
        axfer=axfer,
        asset=asa,
        signer=sender.signer,
        sender=sender.address,
        suggested_params=sp,
    )
    print()

    print(
        f"Step6: borrower {sender.address} repays the loan (interest {payed_interest}) and gets {asa} ASA back "
    )
    app_acct_info = algod_client.account_info(sender.address)
    print(
        f"Info: after {action} borrower {sender.address}",
        app_acct_info["assets"][-2:],
    )
    app_acct_info = algod_client.account_info(app_addr)
    print(f"Info: after {action} app {app_addr}", app_acct_info["assets"])
    app_acct_info = algod_client.account_info(sender2.address)
    print(
        f"Info: after {action} lender {sender2.address}", app_acct_info["assets"][-2:]
    )
    print()
    print(
        f"Info: after {action} borrower {sender.address} local storage {app_client.get_local_state(sender.address)}"
    )
