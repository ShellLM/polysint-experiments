"""
Tests for wallet unmasking logic in utils.py

Uses sys.modules mocking to avoid requiring the web3 library.
"""

import sys
import pytest
from unittest.mock import Mock, patch, MagicMock

# Mock web3 before importing utils
mock_web3 = MagicMock()
mock_web3_instance = MagicMock()
mock_web3.Web3.HTTPProvider.return_value = "mocked_provider"
mock_web3.Web3.return_value = mock_web3_instance
sys.modules['web3'] = mock_web3

# Mock other dependencies
mock_config = MagicMock()
mock_config.Config.RPC_URL = "https://polygon-rpc.com"
sys.modules['config'] = mock_config

mock_logger = MagicMock()
mock_logger.get_logger.return_value = MagicMock()
sys.modules['logger'] = mock_logger

# Now import the module under test
from utils import unmask_proxy


@pytest.fixture
def mock_w3():
    with patch('utils.w3') as mock:
        yield mock


@pytest.fixture
def valid_proxy_address():
    return "0x1234567890abcdef1234567890abcdef12345678"


@pytest.fixture
def expected_owner_address():
    return "0xABCDEF1234567890ABCDEF1234567890ABCDEF12"


class TestValidProxyContract:
    """Tests when the address is a valid proxy contract with an owner."""

    def test_returns_owner_address_from_getowners(self, mock_w3, valid_proxy_address, expected_owner_address):
        padded_owner = "0x000000000000000000000000" + expected_owner_address[2:]
        mock_response = bytes.fromhex(padded_owner[2:])
        
        mock_w3.eth.call.return_value = mock_response
        mock_w3.to_checksum_address.return_value = expected_owner_address
        
        result = unmask_proxy(valid_proxy_address)
        
        mock_w3.eth.call.assert_called_once()
        call_args = mock_w3.eth.call.call_args[0][0]
        assert call_args['data'] == '0x7065c0d4'
        assert result == expected_owner_address

    def test_handles_lowercase_owner_in_response(self, mock_w3, valid_proxy_address):
        owner_lower = "0xabcdef1234567890abcdef1234567890abcdef12"
        owner_checksum = "0xABCDEF1234567890ABCDEF1234567890ABCDEF12"
        
        padded_owner = "0x000000000000000000000000" + owner_lower[2:]
        mock_response = bytes.fromhex(padded_owner[2:])
        
        mock_w3.eth.call.return_value = mock_response
        mock_w3.to_checksum_address.return_value = owner_checksum
        
        result = unmask_proxy(valid_proxy_address)
        assert result == owner_checksum


class TestDirectWallet:
    """Tests when the address is an EOA (not a contract)."""

    def test_returns_direct_wallet_for_empty_response(self, mock_w3, valid_proxy_address):
        mock_w3.eth.call.return_value = b''
        result = unmask_proxy(valid_proxy_address)
        assert result == "Direct Wallet (Not a Proxy)"

    def test_returns_direct_wallet_for_none_response(self, mock_w3, valid_proxy_address):
        mock_w3.eth.call.return_value = None
        result = unmask_proxy(valid_proxy_address)
        assert result == "Direct Wallet (Not a Proxy)"

    def test_returns_direct_wallet_for_falsy_response(self, mock_w3, valid_proxy_address):
        mock_w3.eth.call.return_value = bytes()
        result = unmask_proxy(valid_proxy_address)
        assert result == "Direct Wallet (Not a Proxy)"


class TestExceptionHandling:
    """Tests for various exceptions during the eth_call."""

    def test_handles_contract_revert(self, mock_w3, valid_proxy_address):
        mock_w3.eth.call.side_effect = Exception("execution reverted")
        result = unmask_proxy(valid_proxy_address)
        assert result == "Direct Wallet (Not a Proxy)"

    def test_handles_network_error(self, mock_w3, valid_proxy_address):
        mock_w3.eth.call.side_effect = ConnectionError("RPC endpoint unreachable")
        result = unmask_proxy(valid_proxy_address)
        assert result == "Direct Wallet (Not a Proxy)"

    def test_handles_timeout_error(self, mock_w3, valid_proxy_address):
        mock_w3.eth.call.side_effect = TimeoutError("RPC call timed out")
        result = unmask_proxy(valid_proxy_address)
        assert result == "Direct Wallet (Not a Proxy)"

    def test_handles_value_error(self, mock_w3, valid_proxy_address):
        mock_w3.eth.call.side_effect = ValueError("Invalid address format")
        result = unmask_proxy(valid_proxy_address)
        assert result == "Direct Wallet (Not a Proxy)"

    def test_handles_generic_exception(self, mock_w3, valid_proxy_address):
        mock_w3.eth.call.side_effect = RuntimeError("Unexpected error")
        result = unmask_proxy(valid_proxy_address)
        assert result == "Direct Wallet (Not a Proxy)"

    def test_logs_exception_info(self, mock_w3, valid_proxy_address):
        mock_w3.eth.call.side_effect = Exception("test error")
        
        with patch('utils.log') as mock_log:
            result = unmask_proxy(valid_proxy_address)
            mock_log.info.assert_called_once()
            call_args = mock_log.info.call_args[0][0]
            assert valid_proxy_address in call_args


class TestEdgeCases:
    """Tests for boundary conditions."""

    def test_handles_short_response_bytes(self, mock_w3, valid_proxy_address):
        mock_w3.eth.call.return_value = bytes.fromhex("123456")
        result = unmask_proxy(valid_proxy_address)
        assert result is not None

    def test_handles_all_zero_owner(self, mock_w3, valid_proxy_address):
        zero_address = "0x0000000000000000000000000000000000000000"
        mock_w3.eth.call.return_value = bytes(32)
        mock_w3.to_checksum_address.return_value = zero_address
        
        result = unmask_proxy(valid_proxy_address)
        assert result == zero_address

    def test_checksum_conversion_failure(self, mock_w3, valid_proxy_address):
        mock_w3.eth.call.return_value = bytes(32)
        mock_w3.to_checksum_address.side_effect = ValueError("Invalid hex")
        
        result = unmask_proxy(valid_proxy_address)
        assert result == "Direct Wallet (Not a Proxy)"


class TestGetOwnersSignature:
    """Tests verifying the getOwners() function signature."""

    def test_uses_correct_function_signature(self, mock_w3, valid_proxy_address):
        mock_w3.eth.call.return_value = bytes(32)
        
        unmask_proxy(valid_proxy_address)
        
        call_args = mock_w3.eth.call.call_args[0][0]
        assert call_args['data'] == '0x7065c0d4'

    def test_includes_to_address_in_call(self, mock_w3, valid_proxy_address):
        checksummed = "0x1234567890ABCDEF1234567890ABCDEF12345678"
        mock_w3.to_checksum_address.return_value = checksummed
        mock_w3.eth.call.return_value = bytes(32)
        
        unmask_proxy(valid_proxy_address)
        
        call_args = mock_w3.eth.call.call_args[0][0]
        assert 'to' in call_args


@pytest.mark.parametrize("response_value,expected_result", [
    (b'', "Direct Wallet (Not a Proxy)"),
    (None, "Direct Wallet (Not a Proxy)"),
    (bytes(), "Direct Wallet (Not a Proxy)"),
    (bytes(32), "0x0000000000000000000000000000000000000000"),
])
def test_various_response_values(mock_w3, valid_proxy_address, response_value, expected_result):
    mock_w3.eth.call.return_value = response_value
    
    if response_value and len(response_value) == 32:
        mock_w3.to_checksum_address.return_value = expected_result
    
    result = unmask_proxy(valid_proxy_address)
    assert result == expected_result


@pytest.mark.parametrize("exception_type", [
    ConnectionError, TimeoutError, ValueError, RuntimeError, Exception,
])
def test_various_exception_types(mock_w3, valid_proxy_address, exception_type):
    mock_w3.eth.call.side_effect = exception_type("test")
    result = unmask_proxy(valid_proxy_address)
    assert result == "Direct Wallet (Not a Proxy)"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
