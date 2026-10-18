import { createContext, useContext, useState } from 'react';
import { useChat } from '@ai-sdk/react';
import { DefaultChatTransport } from 'ai';
import { BASE_URL } from '@/services/api';

const AssistantContext = createContext(null);

export function AssistantProvider({ children }) {
  const [isOpen, setIsOpen] = useState(false);
  const [seedContext, setSeedContext] = useState(null);

  const chat = useChat({
    transport: new DefaultChatTransport({
      api: `${BASE_URL}/assistant/chat`,
      credentials: 'include',
    }),
  });

  const openWithContext = (context) => {
    setSeedContext(context);
    setIsOpen(true);
  };

  return (
    <AssistantContext.Provider value={{ isOpen, setIsOpen, seedContext, setSeedContext, openWithContext, chat }}>
      {children}
    </AssistantContext.Provider>
  );
}

export const useAssistant = () => useContext(AssistantContext);

