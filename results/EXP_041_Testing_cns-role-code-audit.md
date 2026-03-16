2026-03-15 12:45:22,768 - llm_consortium.orchestrator - ERROR - Automatic response error for hunter-alpha: Provider returned error
```python
        #!/usr/bin/env python3
        """
        Unit tests for analyst.py market shift calculations
        Focus: _derive_price_behaviour() function and PolyAnalyst integration
        """

        import pytest
        import time
        import sys
        import os
        from unittest.mock import Mock, patch, MagicMock

        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

        from analyst import _derive_price_behaviour, PolyAnalyst


        # ═══════════════════════════════════════════════════════════════════════════════
        # SECTION 1: INPUT VALIDATION
        # ═══════════════════════════════════════════════════════════════════════════════

        class TestInputValidation:
            """Test robustness against invalid, empty, or malformed inputs."""

            @pytest.mark.parametrize("invalid_input,expected_summary", [
                ([], "Insufficient price history (fewer than 2 data points)."),
                (None, "Insufficient price history (fewer than 2 data points)."),
                ([0.5], "Insufficient price history (fewer than 2 data points)."),
                ([None], "Price data could not be parsed."),
                ([None, None], "Price data could not be parsed."),
            ])
            def test_insufficient_data_inputs(self, invalid_input, expected_summary):
                result = _derive_price_behaviour(invalid_input)
                assert result == {"summary": expected_summary}

            @pytest.mark.parametrize("invalid_prices", [
                ["abc", "def"],
                ["not_a_number", 0.5],
                [0.5, "invalid"],
                [""],
                ["  ", "  "],
                ["'; DROP TABLE markets; --", 0.5],
                ["<script>alert('xss')</script>", 0.5],
                [[0.5], [0.6]],
                [{"price": 0.5}, 0.6],
            ])
            def test_unparseable_inputs(self, invalid_prices):
                result = _derive_price_behaviour(invalid_prices)
                assert result == {"summary": "Price data could not be parsed."}

            def test_valid_string_numbers(self):
                result = _derive_price_behaviour(["0.40", "0.50", "0.60"])
                assert result["data_points"] == 3
                assert result["net_shift"] == "+20.0%"

            def test_mixed_int_float_types(self):
                result = _derive_price_behaviour([0.5, 1, 0.75])
                assert result["data_points"] == 3

            def test_boolean_values(self):
                """bool is subclass of int: True=1.0, False=0.0."""
                result = _derive_price_behaviour([False, True])
                assert result["start_price"] == "0.0%"
                assert result["end_price"] == "100.0%"

            def test_scientific_notation(self):
                result = _derive_price_behaviour(["1e-1", "5e-1"])
                assert result["net_shift"] == "+40.0%"

            def test_tuple_input(self):
                result = _derive_price_behaviour((0.4, 0.5, 0.6))
                assert result["data_points"] == 3

            def test_generator_input(self):
                gen = (x * 0.01 for x in range(40, 61))
                result = _derive_price_behaviour(gen)
                assert result["data_points"] == 21


        # ═══════════════════════════════════════════════════════════════════════════════
        # SECTION 2: CORE METRICS
        # ═══════════════════════════════════════════════════════════════════════════════

        class TestCoreMetrics:
            """Test core statistical calculations with exact assertions."""

            @pytest.mark.parametrize("prices,start,end,shift", [
                ([0.40, 0.50], "40.0%", "50.0%", "+10.0%"),
                ([0.50, 0.40], "50.0%", "40.0%", "-10.0%"),
                ([0.50, 0.50], "50.0%", "50.0%", "+0.0%"),
                ([0.10, 0.90], "10.0%", "90.0%", "+80.0%"),
                ([0.90, 0.10], "90.0%", "10.0%", "-80.0%"),
            ])
            def test_two_point_calculations(self, prices, start, end, shift):
                result = _derive_price_behaviour(prices)
                assert result["data_points"] == 2
                assert result["start_price"] == start
                assert result["end_price"] == end
                assert result["net_shift"] == shift

            @pytest.mark.parametrize("prices,high,low", [
                ([0.30, 0.50, 0.40], "50.0%", "30.0%"),
                ([0.60, 0.20, 0.40], "60.0%", "20.0%"),
                ([0.50, 0.50, 0.50], "50.0%", "50.0%"),
                ([0.01, 0.99, 0.50], "99.0%", "1.0%"),
            ])
            def test_high_low(self, prices, high, low):
                result = _derive_price_behaviour(prices)
                assert result["high"] == high
                assert result["low"] == low

            def test_uptrend(self):
                result = _derive_price_behaviour([0.30, 0.35, 0.40, 0.45, 0.50])
                assert result["net_shift"] == "+20.0%"

            def test_downtrend(self):
                result = _derive_price_behaviour([0.70, 0.65, 0.60, 0.55, 0.50])
                assert result["net_shift"] == "-20.0%"

            def test_flat_market(self):
                result = _derive_price_behaviour([0.50, 0.50, 0.50])
                assert result["net_shift"] == "+0.0%"
                assert result["trend_status"] == "No net movement over the window."


        # ═══════════════════════════════════════════════════════════════════════════════
        # SECTION 3: REVERSAL DETECTION (CRITICAL: holding = reversal < 3.0)
        # ═══════════════════════════════════════════════════════════════════════════════

        class TestReversalDetection:
            """Test reversal vs. holding logic with exact boundary conditions."""

            @pytest.mark.parametrize("prices,should_be_holding", [
                ([0.40, 0.80, 0.79], True),    # 1.25% pullback - HOLDING
                ([0.40, 0.80, 0.78], True),    # 2.5% pullback - HOLDING
                ([0.40, 0.80, 0.775], False),  # 3.125% pullback - REVERSAL
                ([0.40, 0.80, 0.70], False),   # 12.5% pullback - REVERSAL
                ([0.60, 0.20, 0.21], True),    # 1% recovery - HOLDING
                ([0.60, 0.20, 0.205], True),   # 2.5% recovery - HOLDING
                ([0.60, 0.20, 0.23], False),   # 15% recovery - REVERSAL
            ])
            def test_reversal_boundaries(self, prices, should_be_holding):
                result = _derive_price_behaviour(prices)
                trend = result["trend_status"]
                if should_be_holding:
                    assert "holding" in trend, f"Expected 'holding' for {prices}, got: {trend}"
                else:
                    assert "reversal" in trend or "recovery" in trend

            def test_exact_3_percent_boundary(self):
                """Exactly 3.0% pullback triggers reversal (holding = reversal < 3.0)."""
                result = _derive_price_behaviour([0.50, 1.00, 0.97])
                assert "showing reversal" in result["trend_status"]

            def test_just_under_3_percent_boundary(self):
                """2.9% pullback should be holding."""
                result = _derive_price_behaviour([0.50, 1.00, 0.971])
                assert "holding" in result["trend_status"]


        # ═══════════════════════════════════════════════════════════════════════════════
        # SECTION 4: MOVE CHARACTER (division-by-zero protection when total_abs == 0)
        # ═══════════════════════════════════════════════════════════════════════════════

        class TestMoveCharacter:
            """Test classification of move character."""

            def test_single_step_spike_n2(self):
                result = _derive_price_behaviour([0.40, 0.80])
                assert "single-step spike" in result["move_character"]

            def test_single_step_spike_larger_window(self):
                result = _derive_price_behaviour([0.40, 0.80, 0.80, 0.80])
                assert "single-step spike" in result["move_character"]

            def test_sharp_concentrated_move(self):
                result = _derive_price_behaviour([0.40, 0.50, 0.60, 0.60, 0.60])
                assert "sharp move concentrated" in result["move_character"]

            def test_gradual_grind(self):
                prices = [0.30 + (i * 0.02) for i in range(21)]
                result = _derive_price_behaviour(prices)
                assert "gradual grind" in result["move_character"]

            def test_flat_market_no_division_by_zero(self):
                """Zero total movement must not crash."""
                result = _derive_price_behaviour([0.50, 0.50, 0.50])
                assert "steps" in result["move_character"]


        # ═══════════════════════════════════════════════════════════════════════════════
        # SECTION 5: JUMP TIMING (off-by-one at 25% and 75% boundaries)
        # ═══════════════════════════════════════════════════════════════════════════════

        class TestJumpTiming:
            """Test timing classification of largest jumps."""

            @pytest.mark.parametrize("spike_at,length,expected", [
                (1, 12, "early"),    # ~9% position
                (3, 12, "early"),    # ~27% position - boundary
                (4, 12, "mid"),      # ~36% position
                (7, 12, "mid"),      # ~64% position
                (8, 12, "late"),     # ~73% position - boundary
                (10, 12, "late"),    # ~91% position
            ])
            def test_jump_timing_positions(self, spike_at, length, expected):
                prices = [0.40] * length
                prices[spike_at] = 0.80
                result = _derive_price_behaviour(prices)
                assert expected in result["largest_single_step"].lower()

            def test_exact_75_percent_boundary(self):
                """75% is NOT < 75, so falls to 'late'."""
                result = _derive_price_behaviour([0.40, 0.40, 0.40, 0.40, 0.80])
                assert "late" in result["largest_single_step"].lower()


        # ═══════════════════════════════════════════════════════════════════════════════
        # SECTION 6: EDGE CASES AND SECURITY
        # ═══════════════════════════════════════════════════════════════════════════════

        class TestEdgeCasesAndSecurity:
            """Test edge cases and security scenarios."""

            @pytest.mark.parametrize("prices", [
                [0.0, 1.0], [1.0, 0.0], [0.0, 0.5, 1.0], [1.0, 0.5, 0.0],
            ])
            def test_extreme_price_values(self, prices):
                result = _derive_price_behaviour(prices)
                assert result["data_points"] == len(prices)

            def test_negative_prices(self):
                result = _derive_price_behaviour([-0.1, 0.5, 0.6])
                assert result["low"] == "-10.0%"

            def test_very_small_changes(self):
                result = _derive_price_behaviour([0.5000, 0.5001, 0.5002, 0.5003])
                assert result["net_shift"] == "+0.03%"

            def test_high_volatility_no_direction(self):
                result = _derive_price_behaviour([0.50, 0.70, 0.30, 0.80, 0.20, 0.50])
                assert result["high"] == "80.0%"
                assert result["low"] == "20.0%"
                assert "0.0%" in result["net_shift"]

            def test_large_dataset_performance(self):
                """DoS prevention: 10k items should complete quickly."""
                prices = [0.50 + (i * 0.0001) for i in range(10000)]
                start = time.perf_counter()
                result = _derive_price_behaviour(prices)
                elapsed = time.perf_counter() - start
                assert result["data_points"] == 10000
                assert elapsed < 2.0

            def test_repeated_calls_consistency(self):
                prices = [0.30, 0.45, 0.60, 0.55, 0.70]
                results = [_derive_price_behaviour(prices) for _ in range(50)]
                for r in results[1:]:
                    assert r == results[0]


        # ═══════════════════════════════════════════════════════════════════════════════
        # SECTION 7: OUTPUT FORMAT CONTRACT
        # ═══════════════════════════════════════════════════════════════════════════════

        class TestOutputFormat:
            """Test output format consistency."""

            EXPECTED_KEYS = {
                "data_points", "start_price", "end_price", "high", "low",
                "net_shift", "largest_single_step", "move_character", "trend_status"
            }

            def test_all_keys_present(self):
                result = _derive_price_behaviour([0.30, 0.40, 0.50])
                assert self.EXPECTED_KEYS.issubset(result.keys())

            def test_no_extra_keys(self):
                result = _derive_price_behaviour([0.30, 0.40, 0.50])
                for key in result.keys():
                    assert key in self.EXPECTED_KEYS

            @pytest.mark.parametrize("field", ["start_price", "end_price", "high", "low", "net_shift"])
            def test_percentage_formatting(self, field):
                result = _derive_price_behaviour([0.333, 0.666])
                assert "%" in result[field]

            def test_data_points_is_integer(self):
                result = _derive_price_behaviour([0.30, 0.40, 0.50])
                assert isinstance(result["data_points"], int)

            def test_price_fields_are_strings(self):
                result = _derive_price_behaviour([0.30, 0.40, 0.50])
                for key in ["start_price", "end_price", "high", "low", "net_shift"]:
                    assert isinstance(result[key], str)

            def test_error_output_safe(self):
                result = _derive_price_behaviour(None)
                assert isinstance(result, dict)
                assert "summary" in result
                assert "traceback" not in str(result).lower()


        # ═══════════════════════════════════════════════════════════════════════════════
        # SECTION 8: POLYANALYST INTEGRATION
        # ═══════════════════════════════════════════════════════════════════════════════

        class TestPolyAnalystIntegration:
            """Test PolyAnalyst integration with price behaviour calculations."""

            @patch('analyst.OpenAI')
            @patch('analyst.PolyResearcher')
            def test_analyze_includes_behaviour_metrics(self, mock_researcher_cls, mock_openai_cls):
                mock_client = MagicMock()
                mock_openai_cls.return_value = mock_client
                mock_response = MagicMock()
                mock_response.choices = [MagicMock(message=MagicMock(content="Analysis"))]
                mock_client.chat.completions.create.return_value = mock_response

                analyst = PolyAnalyst()
                analyst.analyze_market_shift("Will X win?", [0.40, 0.80, 0.79], 10000, use_research=False)

                call_args = mock_client.chat.completions.create.call_args
                user_prompt = call_args[1]['messages'][1]['content']
                assert "40.0%" in user_prompt
                assert "holding" in user_prompt

            @patch('analyst.OpenAI')
            @patch('analyst.PolyResearcher')
            def test_empty_history_handled(self, mock_researcher_cls, mock_openai_cls):
                mock_client = MagicMock()
                mock_openai_cls.return_value = mock_client
                mock_response = MagicMock()
                mock_response.choices = [MagicMock(message=MagicMock(content="OK"))]
                mock_client.chat.completions.create.return_value = mock_response

                analyst = PolyAnalyst()
                analyst.analyze_market_shift("Test", [], 10000, use_research=False)

                call_args = mock_client.chat.completions.create.call_args
                assert "Insufficient price history" in call_args[1]['messages'][1]['content']

            @patch('analyst.OpenAI')
            @patch('analyst.PolyResearcher')
            def test_research_false_skips_network(self, mock_researcher_cls, mock_openai_cls):
                mock_client = MagicMock()
                mock_openai_cls.return_value = mock_client
                mock_response = MagicMock()
                mock_response.choices = [MagicMock(message=MagicMock(content="OK"))]
                mock_client.chat.completions.create.return_value = mock_response

                mock_researcher = MagicMock()
                mock_researcher_cls.return_value = mock_researcher

                analyst = PolyAnalyst()
                analyst.analyze_market_shift("Test", [0.5, 0.6], 10000, use_research=False)

                mock_researcher.get_market_context.assert_not_called()

            @patch('analyst.OpenAI')
            @patch('analyst.PolyResearcher')
            def test_profile_wallet(self, mock_researcher_cls, mock_openai_cls):
                mock_client = MagicMock()
                mock_openai_cls.return_value = mock_client
                mock_response = MagicMock()
                mock_response.choices = [MagicMock(message=MagicMock(content="Profile"))]
                mock_client.chat.completions.create.return_value = mock_response

                analyst = PolyAnalyst()
                result = analyst.profile_wallet("0x1234", "Owner", ["Trade 1"])
                assert result == "Profile"
                assert mock_client.chat.completions.create.called

            @patch('analyst.OpenAI')
            @patch('analyst.PolyResearcher')
            def test_profile_wallet_empty_trades(self, mock_researcher_cls, mock_openai_cls):
                mock_client = MagicMock()
                mock_openai_cls.return_value = mock_client
                mock_response = MagicMock()
                mock_response.choices = [MagicMock(message=MagicMock(content="Insufficient"))]
                mock_client.chat.completions.create.return_value = mock_response

                analyst = PolyAnalyst()
                analyst.profile_wallet("0x1234", "Owner", [])

                call_args = mock_client.chat.completions.create.call_args
                assert "RECENT TRADES: []" in call_args[1]['messages'][1]['content']


        # ═══════════════════════════════════════════════════════════════════════════════
        # SECTION 9: PERFORMANCE SCALING
        # ═══════════════════════════════════════════════════════════════════════════════

        class TestPerformance:
            """Test performance scaling characteristics."""

            @pytest.mark.parametrize("size", [10, 100, 1000, 5000])
            def test_scaling(self, size):
                prices = [0.50 + (i * 0.0001) for i in range(size)]
                start = time.perf_counter()
                result = _derive_price_behaviour(prices)
                elapsed = time.perf_counter() - start
                assert result["data_points"] == size
                assert elapsed < 2.0


        if __name__ == "__main__":
            pytest.main([__file__, "-v", "--tb=short", "-x"])
        ```

        **Test Coverage Summary:**

        | Section | Tests | Focus |
        |---------|-------|-------|
        | Input Validation | 12 | Adversarial inputs, type safety, null handling |
        | Core Metrics | 8 | Exact calculations, high/low detection |
        | Reversal Detection | 9 | 3% boundary precision, uptrend/downtrend |
        | Move Character | 5 | Spike/sharp/gradual classification, div-by-zero |
        | Jump Timing | 7 | Early/mid/late position, boundary precision |
        | Edge Cases & Security | 7 | Extreme values, DoS prevention, consistency |
        | Output Format | 6 | Key validation, type safety, safe errors |
        | Integration | 5 | PolyAnalyst pipeline, profile_wallet, mocking |
        | Performance | 4 | Scaling verification |

        **Total: 63 test cases**
