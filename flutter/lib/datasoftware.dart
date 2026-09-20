// ===========================================================================
// DataSoftware custom client - first-run permanent password
// ===========================================================================
//
// The Dart half of the customisation. The Rust half is src/datasoftware.rs;
// see DATASOFTWARE_BUILD.md.
//
// Why this exists: RustDesk stores the permanent password hashed, which is why
// the main window shows "-" instead of it once one is set. The plaintext only
// exists at the moment it is chosen, so an unattended machine either has a
// password somebody wrote down at install time, or no usable one at all.
//
// So on the first run of an installed client this generates a strong random
// password, sets it, and shows it once. The password is per machine: one
// compromised endpoint does not expose any other. It is never written to disk
// in plaintext and never leaves the machine.
//
// If the technician dismisses the dialog without confirming, the next start
// generates and shows a *new* password rather than trying to recover the old
// one, which is impossible. So what the dialog shows is always the password
// that is actually in effect.
//
// The only hook into upstream code is one call in
// flutter/lib/desktop/pages/desktop_home_page.dart's initState.

import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_hbb/common.dart';
import 'package:flutter_hbb/models/platform_model.dart';
// GetX supplies the .paddingOnly() widget extension used across the app.
import 'package:get/get.dart';

/// Set once the technician confirms they have stored the password, so the
/// dialog is not shown again.
///
/// It also gates the permanent-password lock: `apply_builtin_config()` in
/// src/datasoftware.rs turns on `disable-change-permanent-password` only when
/// this is set, because that flag would otherwise block the generator below as
/// well. Must stay identical to `INITIAL_PASSWORD_ACK` there.
const String kDataSoftwareInitialPasswordAck =
    'datasoftware-initial-password-acknowledged';

/// Ambiguous characters are left out on purpose: this password gets read off a
/// screen and typed somewhere else, and 0/O and 1/l/I are where that goes
/// wrong. 14 characters from this 55 character alphabet is about 81 bits.
const String _passwordAlphabet =
    'abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789';
const int _passwordLength = 14;

String generateDataSoftwarePassword() {
  // Random.secure() is the OS CSPRNG. Never use the default Random() here.
  final rng = Random.secure();
  return List.generate(
    _passwordLength,
    (_) => _passwordAlphabet[rng.nextInt(_passwordAlphabet.length)],
  ).join();
}

/// Generate, apply and display the permanent password, unless that has already
/// been done on this machine. Safe to call on every start.
Future<void> ensureInitialPermanentPassword() async {
  // Only for a real installation. A portable run is someone testing the
  // client, and its configuration does not persist.
  if (!bind.mainIsInstalled()) return;
  if (bind.mainGetLocalOption(key: kDataSoftwareInitialPasswordAck) == 'Y') {
    return;
  }

  final password = generateDataSoftwarePassword();
  final ok = await bind.mainSetPermanentPasswordWithResult(password: password);
  if (!ok) {
    // Happens if changing the permanent password is disabled. Nothing sensible
    // to show, and no point retrying on every start.
    debugPrint('DataSoftware: could not set the initial permanent password');
    return;
  }

  _showPasswordDialog(password);
}

void _showPasswordDialog(String password) {
  gFFI.dialogManager.show((setState, close, context) {
    return CustomAlertDialog(
      title: Row(
        children: [
          Icon(Icons.key, color: MyTheme.accent),
          Text(translate('Permanent password for this computer'))
              .paddingOnly(left: 10),
        ],
      ),
      content: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(translate('datasoftware_initial_password_tip')),
          const SizedBox(height: 16),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 14),
            decoration: BoxDecoration(
              // Deliberately not ColorScheme.surfaceVariant: that member is
              // deprecated and would break on a later Flutter bump.
              color: Theme.of(context).brightness == Brightness.dark
                  ? Colors.white10
                  : Colors.black12,
              borderRadius: BorderRadius.circular(8),
            ),
            child: Row(
              children: [
                Expanded(
                  child: SelectableText(
                    password,
                    style: const TextStyle(
                      // "monospace" is not a real family on Windows, so name a
                      // font that ships with it and keep the generic as a
                      // fallback for the other platforms.
                      fontFamily: 'Consolas',
                      fontFamilyFallback: ['Courier New', 'monospace'],
                      fontSize: 20,
                      letterSpacing: 2,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
                IconButton(
                  icon: const Icon(Icons.copy_rounded),
                  tooltip: translate('Copy'),
                  onPressed: () {
                    Clipboard.setData(ClipboardData(text: password));
                    showToast(translate('Copied'));
                  },
                ),
              ],
            ),
          ),
          const SizedBox(height: 14),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(Icons.warning_amber_rounded,
                  size: 18, color: Colors.orange.shade700),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  translate('datasoftware_initial_password_warning'),
                  style: TextStyle(color: Colors.orange.shade800),
                ),
              ),
            ],
          ),
        ],
      ),
      actions: [
        dialogButton(
          'I have saved the password',
          icon: const Icon(Icons.done_rounded),
          onPressed: () async {
            await bind.mainSetLocalOption(
                key: kDataSoftwareInitialPasswordAck, value: 'Y');
            close();
          },
        ),
      ],
    );
  });
}
