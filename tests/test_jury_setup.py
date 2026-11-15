"""The setup helper must preserve existing work and never imply native proof."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("jury_setup_under_test", SOURCE / "deployment/jury_setup.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class JurySetupTests(unittest.TestCase):
    image = "sha256:" + "a" * 64
    ident = "b" * 32

    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="chronos-jury-setup-test-")
        self.addCleanup(self.scratch.cleanup)
        self.parent = Path(self.scratch.name)
        self.cache = self.parent / "model-cache"
        self.cache.mkdir()
        self.cache_marker = self.cache / "preserve-model-cache.txt"
        self.cache_marker.write_text("existing model cache remains untouched", encoding="utf-8")
        self.target = self.parent / "jury"

    def prepare(self, **kwargs):
        opts = dict(deployment_id=self.ident, source=SOURCE)
        opts.update(kwargs)
        return setup.prepare(str(self.target), self.image, str(self.cache), 53139, **opts)

    def receipt(self):
        return json.loads((self.target / setup.RECEIPT).read_text(encoding="utf-8"))

    def rewrite_receipt(self, value):
        (self.target / setup.RECEIPT).write_text(json.dumps(value), encoding="utf-8")

    def test_prepares_both_profiles_and_pristine_stage_without_execution(self):
        before = self.cache_marker.read_bytes()
        result = self.prepare()
        verified = setup.verify(str(self.target), source=SOURCE)
        self.assertEqual(result, verified)
        self.assertEqual(result["mode"], "LIVE_LOCAL_SETUP_ONLY")
        self.assertFalse(result["installed"])
        self.assertFalse(result["allowances_initialized"])
        self.assertEqual((result["accounts_created"], result["services_started"], result["model_calls"]), (0, 0, 0))
        e1 = json.loads((self.target / "profiles/e1.json").read_bytes())
        c2 = json.loads((self.target / "profiles/c2.json").read_bytes())
        self.assertEqual(e1["deployment_id"], c2["deployment_id"])
        self.assertEqual(e1["request_limit"], 12)
        self.assertEqual(c2["request_limit"], 24)
        self.assertEqual(self.cache_marker.read_bytes(), before)
        self.assertEqual(list((self.target / "stage/data").iterdir()), [])
        self.assertEqual(list((self.target / "stage/guard").iterdir()), [])

    def test_second_prepare_preserves_previous_workspace(self):
        self.prepare()
        path = self.target / setup.RECEIPT
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "WORKSPACE_ALREADY_EXISTS"):
            self.prepare()
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_rejects_mutable_image_or_provider_port_before_writes(self):
        for image, port in (("iris:latest", 53139), (self.image, 11512), (self.image, 11514), (self.image, True)):
            with self.subTest(image=image, port=port):
                with self.assertRaises(ValueError):
                    setup.prepare(str(self.target), image, str(self.cache), port, source=SOURCE)
                self.assertFalse(self.target.exists())

    def test_rejects_invalid_identity_before_writes(self):
        with self.assertRaisesRegex(ValueError, "INVALID_DEPLOYMENT_ID"):
            self.prepare(deployment_id="invalid")
        self.assertFalse(self.target.exists())

    def test_rejects_model_cache_inside_new_workspace(self):
        # Here the existing cache would become an ancestor of the new workspace.
        with self.assertRaisesRegex(ValueError, "WORKSPACE_OVERLAPS_MODEL_CACHE"):
            setup.prepare(str(self.cache / "nested"), self.image, str(self.cache), 53139, source=SOURCE)
        self.assertFalse((self.cache / "nested").exists())

    def test_changed_mount_or_expanded_gpu_configuration_is_rejected(self):
        self.prepare()
        original = self.receipt()
        for key, value in (("CHRONOS_DATA", str(self.cache)), ("CHRONOS_GPU_DEVICE_ID", "all"),
                           ("CHRONOS_MODEL_MEMORY", "32g")):
            altered = copy.deepcopy(original)
            altered["environment"][key] = value
            self.rewrite_receipt(altered)
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, "COMPOSE_BINDING_CHANGED"):
                    setup.verify(str(self.target), source=SOURCE)

    def test_expanded_compose_layout_is_rejected(self):
        self.prepare()
        altered = self.receipt()
        altered["compose_files"].append("unreviewed.yaml")
        self.rewrite_receipt(altered)
        with self.assertRaisesRegex(ValueError, "COMPOSE_LAYOUT_CHANGED"):
            setup.verify(str(self.target), source=SOURCE)

    def test_modified_conversation_profile_is_rejected(self):
        self.prepare()
        profile_path = self.target / "profiles/c2.json"
        changed = json.loads(profile_path.read_bytes())
        changed["request_limit"] = 99
        profile_path.write_text(json.dumps(changed), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "PROFILE_DIGEST_CHANGED"):
            setup.verify(str(self.target), source=SOURCE)

    def test_used_workspace_cannot_be_reported_as_pristine(self):
        self.prepare()
        (self.target / "chat-state/used-state").write_text("keep me", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "WORKSPACE_ALREADY_USED"):
            setup.verify(str(self.target), source=SOURCE)
        self.assertEqual((self.target / "chat-state/used-state").read_text(), "keep me")

    def test_partial_output_is_preserved_without_automatic_retry(self):
        _, staging, _, _ = setup.modules(SOURCE)
        with patch.object(staging, "stage", side_effect=ValueError("injected failure")):
            with self.assertRaisesRegex(ValueError, "WORKSPACE_FAILED_PARTIAL_PRESERVED"):
                self.prepare()
        self.assertTrue((self.target / "bundle/bundle-manifest.json").is_file())
        self.assertFalse((self.target / setup.RECEIPT).exists())
        with self.assertRaisesRegex(ValueError, "WORKSPACE_ALREADY_EXISTS"):
            self.prepare()

    def test_imported_tools_from_another_checkout_are_rejected(self):
        wrong = ModuleType("application_bundle")
        wrong.__file__ = str(self.parent / "another-checkout/application_bundle.py")
        with patch.dict(setup.sys.modules, {"application_bundle": wrong}):
            with self.assertRaisesRegex(ValueError, "IMPORT_SOURCE_MISMATCH"):
                setup.modules(SOURCE)

    def test_repeated_same_namespace_path_is_allowed_but_another_root_is_not(self):
        setup.modules(SOURCE)
        package = setup.sys.modules['chronos_transport']
        same_root = str(SOURCE / 'src/chronos_transport')
        with patch.object(package, '__path__', [same_root, same_root]):
            self.assertEqual(setup.modules(SOURCE)[0].__file__, str(SOURCE / 'tools/application_bundle.py'))
        with patch.object(package, '__path__', [same_root, str(self.parent / 'foreign-package')]):
            with self.assertRaisesRegex(ValueError, 'IMPORT_SOURCE_MISMATCH'):
                setup.modules(SOURCE)

    def test_invalid_environment_has_controlled_error(self):
        self.prepare()
        original = self.receipt()
        for value in (None, [], "unexpected"):
            changed = copy.deepcopy(original)
            changed["environment"] = value
            self.rewrite_receipt(changed)
            with self.subTest(environment=value):
                with self.assertRaisesRegex(ValueError, "INVALID_COMPOSE_ENVIRONMENT"):
                    setup.verify(str(self.target), source=SOURCE)

    def test_coherent_e1_policy_rewrite_cannot_expand_model_or_allowance(self):
        self.prepare()
        bundle, _, local, _ = setup.modules(SOURCE)
        original = self.receipt()
        original_profile = json.loads((self.target / "profiles/e1.json").read_bytes())
        stage_receipt_path = self.target / "stage/stage-receipt.json"
        original_stage_receipt = json.loads(stage_receipt_path.read_bytes())
        for key, value in (("model", "other-model"), ("request_limit", 1000)):
            changed_profile = copy.deepcopy(original_profile)
            changed_profile[key] = value
            raw = bundle.json_bytes(changed_profile)
            digest = local.Profile.parse(raw).digest
            for path in (self.target / "profiles/e1.json", self.target / "stage/profile.json"):
                path.write_bytes(raw)
            changed_stage_receipt = copy.deepcopy(original_stage_receipt)
            changed_stage_receipt["profile_sha256"] = digest
            changed_stage_receipt["profile_file_sha256"] = hashlib.sha256(raw).hexdigest()
            stage_receipt_path.write_bytes(bundle.json_bytes(changed_stage_receipt))
            changed_receipt = copy.deepcopy(original)
            changed_receipt["e1_profile_sha256"] = digest
            self.rewrite_receipt(changed_receipt)
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, "DECISION_PROFILE_CHANGED"):
                    setup.verify(str(self.target), source=SOURCE)


if __name__ == "__main__":
    unittest.main()
