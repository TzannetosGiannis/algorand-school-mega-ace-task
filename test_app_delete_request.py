import pytest
from algosdk import transaction
from algosdk.atomic_transaction_composer import (
    AtomicTransactionComposer,
    TransactionWithSigner,
)
from algosdk.dryrun_results import DryrunResponse
from algosdk.encoding import encode_address
from beaker import *
from beaker import sandbox, client

##########
# fixtures
##########


@pytest.fixture(scope="module")
def create_app():
    global accounts
    global borrower
    global lender
    global algod_client
    global app_client
    global creator
    global app_id
    global app_addr
    accounts = sandbox.kmd.get_accounts()

    borrower = accounts[0]
    lender = accounts[1]
    creator = accounts[2]

    algod_client = sandbox.get_algod_client()

    app_client = client.ApplicationClient(
        app=open("./artifacts/application.json").read(),
        client=sandbox.get_algod_client(),
        signer=creator.signer,
        sender=creator.address,
    )
    app_id, app_addr, _ = app_client.create()
    app_client.fund(100001 * consts.milli_algo)


@pytest.fixture(scope="module")
def opt_in():
    global asa
    global asa2
    global asa2_supply
    atc = AtomicTransactionComposer()

    # Create ASA for borrower
    asa_create_borrower = TransactionWithSigner(
        txn=transaction.AssetCreateTxn(
            sender=borrower.address,
            total=1,
            decimals=0,
            default_frozen=False,
            unit_name="Borrower",
            asset_name="Borrower ASA",
            sp=app_client.get_suggested_params(),
        ),
        signer=borrower.signer,
    )

    atc.add_transaction(asa_create_borrower)
    tx_id = atc.execute(sandbox.get_algod_client(), 3).tx_ids[0]
    asa = sandbox.get_algod_client().pending_transaction_info(tx_id)["asset-index"]

    # Create ASA lender
    asa2_supply = 100000000
    atc2 = AtomicTransactionComposer()
    asa_create_lender = TransactionWithSigner(
        txn=transaction.AssetCreateTxn(
            sender=lender.address,
            total=asa2_supply,
            decimals=0,
            default_frozen=False,
            unit_name="Lender",
            asset_name="Lender ASA",
            sp=app_client.get_suggested_params(),
        ),
        signer=lender.signer,
    )

    atc2.add_transaction(asa_create_lender)
    tx_id = atc2.execute(sandbox.get_algod_client(), 3).tx_ids[0]
    asa2 = sandbox.get_algod_client().pending_transaction_info(tx_id)["asset-index"]

    app_client.opt_in(
        sender=borrower.address,
        signer=borrower.signer,
    )


@pytest.fixture(scope="module")
def opt_in_nft():
    global sp
    sp = app_client.get_suggested_params()
    sp.fee = sp.min_fee * 3
    app_client.call(
        "opt_in_nft",
        sender=borrower.address,
        signer=borrower.signer,
        suggested_params=sp,
        axfer=asa,
    )

    app_client.call(
        "opt_in_nft",
        sender=lender.address,
        signer=lender.signer,
        suggested_params=sp,
        axfer=asa2,
    )

    atc3 = AtomicTransactionComposer()
    axfer = TransactionWithSigner(
        txn=transaction.AssetTransferTxn(
            sender=borrower.address,
            receiver=borrower.address,
            index=asa2,
            amt=0,
            sp=sp,
        ),
        signer=borrower.signer,
    )

    atc3.add_transaction(axfer)
    atc3.execute(sandbox.get_algod_client(), 3)

    atc4 = AtomicTransactionComposer()
    axfer = TransactionWithSigner(
        txn=transaction.AssetTransferTxn(
            sender=lender.address,
            receiver=lender.address,
            index=asa,
            amt=0,
            sp=sp,
        ),
        signer=lender.signer,
    )

    atc4.add_transaction(axfer)
    atc4.execute(sandbox.get_algod_client(), 3).tx_ids[0]


@pytest.fixture(scope="module")
def request_loan():
    global asa2
    global asa
    global request_amount
    global interest
    global borrower
    global app_addr
    global sp
    global loan_duration
    global initial_amount
    loan_duration = 1000
    request_amount = 10
    interest = 1

    axfer = TransactionWithSigner(
        txn=transaction.AssetTransferTxn(
            sender=borrower.address,
            receiver=app_addr,
            index=asa,
            amt=1,
            sp=app_client.get_suggested_params(),
        ),
        signer=borrower.signer,
    )

    app_client.call(
        "request_loan",
        request_token=asa2,  # fix this
        quantity=request_amount,
        duration=loan_duration,
        interest=interest,
        axfer=axfer,
        sender=borrower.address,
        suggested_params=sp,
        signer=borrower.signer,
    )

    initial_amount = 40000
    atc = AtomicTransactionComposer()
    axfer = TransactionWithSigner(
        txn=transaction.AssetTransferTxn(
            sender=lender.address,
            receiver=borrower.address,
            index=asa2,
            amt=initial_amount,
            sp=sp,
        ),
        signer=lender.signer,
    )

    atc.add_transaction(axfer)
    atc.execute(sandbox.get_algod_client(), 3)


@pytest.fixture(scope="module")
def accept_loan():
    axfer = TransactionWithSigner(
        txn=transaction.AssetTransferTxn(
            sender=lender.address,
            receiver=borrower.address,
            index=asa2,
            amt=request_amount,
            sp=app_client.get_suggested_params(),
        ),
        signer=lender.signer,
    )

    app_client.call(
        "accept_loan",
        borrower=borrower.address,
        sender=lender.address,
        signer=lender.signer,
        axfer=axfer,
        suggested_params=sp,
    )


@pytest.fixture(scope="module")
def delete_request():
    app_client.call(
        "delete_request",
        sender=borrower.address,
        signer=borrower.signer,
        asset=asa,
        suggested_params=sp,
    )


##############
# create tests
##############


@pytest.mark.create
def test_create_highest_bidder(create_app):
    global app_id
    assert app_id != 0


#############
# OptIn tests
#############


@pytest.mark.opt_in
def test_opt_in(create_app, opt_in):
    global asa
    assert asa != 0


@pytest.mark.opt_in
def test_opt_in(create_app, opt_in):
    assert asa2 != 0


@pytest.mark.opt_in
def test_opt_in(create_app, opt_in):
    assert app_client.get_local_state(borrower.address) != {}


#####################
# opt_in_nfts tests
#####################


@pytest.mark.opt_in_nft
def test_opt_in_nft(create_app, opt_in, opt_in_nft):
    app_acct_info = algod_client.account_info(app_addr)
    asset = (
        str(app_acct_info["assets"][-2]["asset-id"])
        + "_"
        + str(app_acct_info["assets"][-2]["amount"])
    )
    assert asset == str(asa) + "_" + str(0)


@pytest.mark.opt_in_nft
def test_opt_in_nft2(create_app, opt_in, opt_in_nft):
    app_acct_info = algod_client.account_info(app_addr)
    asset = (
        str(app_acct_info["assets"][-1]["asset-id"])
        + "_"
        + str(app_acct_info["assets"][-1]["amount"])
    )
    assert asset == str(asa2) + "_" + str(0)


@pytest.mark.opt_in_nft
def test_opt_in_nft3(create_app, opt_in, opt_in_nft):
    app_acct_info = algod_client.account_info(borrower.address)
    asset = (
        str(app_acct_info["assets"][-1]["asset-id"])
        + "_"
        + str(app_acct_info["assets"][-1]["amount"])
    )
    assert asset == str(asa2) + "_" + str(0)


@pytest.mark.opt_in_nft
def test_opt_in_nft4(create_app, opt_in, opt_in_nft):
    app_acct_info = algod_client.account_info(lender.address)
    asset = (
        str(app_acct_info["assets"][-2]["asset-id"])
        + "_"
        + str(app_acct_info["assets"][-2]["amount"])
    )
    assert asset == str(asa) + "_" + str(0)


#####################
# request_loan tests
#####################


@pytest.mark.request_loan
def test_request_loan(create_app, opt_in, opt_in_nft, request_loan):
    app_acct_info = algod_client.account_info(app_addr)
    asset = (
        str(app_acct_info["assets"][-2]["asset-id"])
        + "_"
        + str(app_acct_info["assets"][-2]["amount"])
    )

    assert asset == str(asa) + "_" + str(1)


@pytest.mark.request_loan
def test_request_loan2(create_app, opt_in, opt_in_nft, request_loan):
    assert app_client.get_local_state(borrower.address)["duration"] == loan_duration


#####################
# delete_request tests
#####################


@pytest.mark.delete_request
def test_delete_request1(create_app, opt_in, opt_in_nft, request_loan, delete_request):
    assert app_client.get_local_state(borrower.address)["lender"] == ""


@pytest.mark.delete_request
def test_delete_request2(create_app, opt_in, opt_in_nft, request_loan, delete_request):
    app_acct_info = algod_client.account_info(borrower.address)
    asset = (
        str(app_acct_info["assets"][-2]["asset-id"])
        + "_"
        + str(app_acct_info["assets"][-2]["amount"])
    )

    assert asset == str(asa) + "_" + str(1)
