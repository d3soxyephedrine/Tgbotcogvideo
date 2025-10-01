"""
Custom NOWPayments API wrapper with proper JSON support
"""
import requests
import logging

logger = logging.getLogger(__name__)

class NOWPaymentsWrapper:
    BASE_URI = "https://api.nowpayments.io/v1/"
    
    def __init__(self, api_key):
        self.api_key = api_key
        self.session = requests.Session()
    
    def create_payment(self, price_amount, price_currency, pay_currency, **kwargs):
        """
        Create a payment with proper JSON encoding
        """
        url = f"{self.BASE_URI}payment"
        headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json"
        }
        
        payload = {
            "price_amount": price_amount,
            "price_currency": price_currency,
            "pay_currency": pay_currency,
            **kwargs
        }
        
        logger.debug(f"Creating payment with payload: {payload}")
        
        response = None
        try:
            response = self.session.post(url=url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            # Log the actual error response
            if response is not None:
                try:
                    error_detail = response.json()
                    logger.error(f"NOWPayments API error: {error_detail}")
                    raise Exception(f"NOWPayments API error: {error_detail.get('message', str(e))}")
                except:
                    logger.error(f"NOWPayments API error: {response.text}")
                    raise Exception(f"NOWPayments API error: {response.text}")
            else:
                raise Exception(f"NOWPayments API error: {str(e)}")
    
    def currencies(self, fixed_rate=True):
        """
        Get available currencies
        """
        url = f"{self.BASE_URI}currencies?fixed_rate={fixed_rate}"
        headers = {"x-api-key": self.api_key}
        
        response = self.session.get(url=url, headers=headers)
        response.raise_for_status()
        return response.json()
    
    def payment_status(self, payment_id):
        """
        Get payment status
        """
        url = f"{self.BASE_URI}payment/{payment_id}"
        headers = {"x-api-key": self.api_key}
        
        response = self.session.get(url=url, headers=headers)
        response.raise_for_status()
        return response.json()
    
    def minimum_payment_amount(self, currency_from="usd", currency_to="btc"):
        """
        Get minimum payment amount for a currency pair
        """
        url = f"{self.BASE_URI}min-amount?currency_from={currency_from}&currency_to={currency_to}"
        headers = {"x-api-key": self.api_key}
        
        response = self.session.get(url=url, headers=headers)
        response.raise_for_status()
        return response.json()
