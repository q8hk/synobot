import unittest

from synobot.authorization import AuthorizationPolicy, Role


class AuthorizationPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = AuthorizationPolicy.create(
            administrators=[1], operators=[2], viewers=[3]
        )

    def test_resolves_each_configured_role(self):
        self.assertEqual(self.policy.role_for(1), Role.ADMIN)
        self.assertEqual(self.policy.role_for(2), Role.OPERATOR)
        self.assertEqual(self.policy.role_for(3), Role.VIEWER)

    def test_unknown_user_is_rejected(self):
        with self.assertRaises(PermissionError):
            self.policy.role_for(99)

    def test_group_chat_is_disabled_by_default(self):
        with self.assertRaisesRegex(PermissionError, "group chats"):
            self.policy.role_for(1, chat_type="group")

    def test_minimum_role_is_enforced(self):
        self.assertEqual(self.policy.require(1, Role.ADMIN), Role.ADMIN)
        self.assertEqual(self.policy.require(2, Role.VIEWER), Role.OPERATOR)
        with self.assertRaisesRegex(PermissionError, "required role"):
            self.policy.require(3, Role.OPERATOR)


if __name__ == "__main__":
    unittest.main()
