# Builder Verification Guide

This guide will help you get verified status on Polymarket to access **3000 requests/day** instead of the default 200 requests/day.

## Why Get Verified?

| Feature | Unverified | Verified |
|---------|------------|-----------|
| Rate Limit | 200 req/day | **3000 req/day** |
| Builder Leaderboard | ❌ | ✅ |
| Order Attribution | ❌ | ✅ |
| Fee Share | ❌ | ✅ |
| Weekly Rewards | ❌ | ✅ |

## Prerequisites

Before you start, ensure you have:
- [x] Polymarket account created
- [x] Python bot installed and configured
- [x] Basic understanding of environment variables

## Step-by-Step Verification

### Step 1: Create Builder Account

1. **Go to Builder Settings**:
   - Navigate to [polymarket.com/settings?tab=builder](https://polymarket.com/settings?tab=builder)
   - Or click your profile image → Select "Builders"

2. **Set Your Builder Identity**:
   - Upload a profile picture (optional but recommended for leaderboard)
   - Set your builder name (displayed publicly)

3. **Note Your Builder Address**:
   - Copy your builder address (used for identification)

### Step 2: Generate Builder API Keys

1. **Navigate to Builder Keys Section**:
   - Scroll down to "Builder Keys" section
   - Click the "+ Create New" button

2. **Save Your Credentials**:
   The system will generate three credentials:
   ```
   BUILDER_API_KEY:    xxxxxxxx-xxxx-xxxx-xxxx
   BUILDER_SECRET:       yyyyyyyy-yyyy-yyyy-yyyy
   BUILDER_PASSPHRASE: zzzzzzzz-zzzz-zzzz-zzzz
   ```

3. **Security Important**:
   - ✅ Save these credentials securely
   - ✅ Never commit to version control
   - ✅ Never share publicly
   - ✅ Store in environment variables or secrets manager

### Step 3: Configure Your Bot

1. **Update `.env` file**:
   ```env
   # Enable builder mode
   BUILDER_ENABLED=True

   # Add your builder credentials
   BUILDER_API_KEY=your_actual_api_key_here
   BUILDER_SECRET=your_actual_secret_here
   BUILDER_PASSPHRASE=your_actual_passphrase_here
   ```

2. **Install Builder SDK**:
   ```bash
   pip install py-builder-signing-sdk
   ```

3. **Restart Your Bot**:
   ```bash
   python main.py
   ```

### Step 4: Verify It's Working

1. **Check Bot Logs**:
   Look for this message:
   ```
   Polymarket client initialized with Builder credentials (verified mode)
   ```

2. **Check Your Builder Profile**:
   - Go back to [polymarket.com/settings?tab=builder](https://polymarket.com/settings?tab=builder)
   - Check "Current Tier" - should show "Verified"

3. **Monitor API Usage**:
   - The bot will now make requests with builder attribution
   - Rate limit is 3000 requests/day (vs 200 before)

## Testing Your Setup

### Test 1: Verify Client Initialization

Start the bot and check logs:

**Success (Verified Mode)**:
```
✅ Polymarket client initialized with Builder credentials (verified mode)
```

**Unverified Mode** (if builder credentials are missing or invalid):
```
⚠️ Failed to initialize Builder credentials: [error message], falling back to standard mode
⚠️ Polymarket client initialized (unverified mode - 200 req/day limit)
```

### Test 2: Check Rate Limit

After the bot runs for a while, monitor the request rate:
- **Verified**: Should handle many more requests without hitting rate limits
- **Unverified**: Will hit 429 errors after ~200 requests

### Test 3: Check Builder Leaderboard

After making some trades:
1. Go to [builders.polymarket.com](https://builders.polymarket.com/)
2. Search for your builder name
3. You should see your stats (volume, active users, etc.)

## Common Issues

### Issue 1: "Failed to initialize Builder credentials"

**Symptom**:
```
Failed to initialize Builder credentials: [error], falling back to standard mode
```

**Solutions**:
1. Verify `py-builder-signing-sdk` is installed:
   ```bash
   pip install py-builder-signing-sdk
   ```

2. Check all builder credentials are set in `.env`:
   - `BUILDER_API_KEY` must not be empty
   - `BUILDER_SECRET` must not be empty
   - `BUILDER_PASSPHRASE` must not be empty

3. Ensure `BUILDER_ENABLED=True`:
   ```env
   BUILDER_ENABLED=True
   ```

### Issue 2: "Invalid signature errors"

**Symptom**:
```
Invalid signature errors from CLOB API
```

**Solutions**:
1. Verify builder credentials match exactly what's in your builder profile
2. Regenerate API keys if needed
3. Restart the bot after updating credentials

### Issue 3: Rate limit still 200 req/day

**Symptom**:
Still hitting rate limits after enabling builder credentials

**Solutions**:
1. Verify your tier in builder profile shows "Verified"
2. Check logs confirm "verified mode" initialization
3. Wait 24 hours for tier to update after first use

### Issue 4: Not showing on Builder Leaderboard

**Symptom**:
Your builder isn't visible on the leaderboard

**Solutions**:
1. Need at least some volume to appear
2. Check builder name matches in profile
3. Leaderboard updates periodically (may take time)

## Security Best Practices

1. **Never commit credentials** to Git or any public repository
2. **Use different keys** for development vs production
3. **Rotate keys periodically** for better security
4. **Monitor key usage** in builder profile
5. **Revoke unused keys** in builder profile

## Rate Limit Calculator

With 3000 requests/day, here's how many requests you can make:

| Time Period | Requests |
|------------|----------|
| Per Hour | 125 |
| Per Minute | 2.08 |
| Per Second | 0.035 |

**Note**: The bot scans every 500ms (2x/second) by default, which is well within limits when verified.

## Next Steps

After verification:

1. [ ] Monitor your bot's performance on Builder Leaderboard
2. [ ] Check volume and active users metrics
3. [ ] Compete for weekly builder rewards
4. [ ] Earn fee share on routed orders
5. [ ] Track performance via Data API

## Additional Resources

- [Builder Profile](https://polymarket.com/settings?tab=builder)
- [Builder Leaderboard](https://builders.polymarket.com/)
- [Order Attribution Docs](https://docs.polymarket.com/developers/builders/order-attribution)
- [CLOB API Documentation](https://docs.polymarket.com/developers/CLOB/introduction)

## Support

If you encounter issues:
1. Check this guide's troubleshooting section
2. Review Polymarket documentation
3. Check bot logs in `logs/` directory
4. Verify environment variables are set correctly
